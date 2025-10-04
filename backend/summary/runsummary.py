#!/usr/bin/env python3
"""CLI unificado: PDF -> (GROBID) -> summary_and_content/

NUEVA ESTRUCTURA por paper (objetivo solicitado):
    <base_dir>/<paper_id>/
        graph/                     (pipeline KG previo, no se toca aquí)
        summary_and_content/
            <paper_id>.content.json  (antes *.grobid.content.json, renombrado)
            summary.json             (salida LLM enriquecida)
            figures/                 (imágenes normalizadas fig_1.* ...)

Uso básico:
    python -m summary.runsummary paper.pdf --paper-id PMC123 --base-dir processed_grobid_pdfs

Compatibilidad legacy (opcional): añadir --legacy-session para producir también
la antigua sesión chatsession_<slug>_/ con meta.json. Esto permite no romper
integraciones previas mientras se migra totalmente.

Exit codes:
    0 OK
    1 argumentos / archivo no encontrado
    2 fallo GROBID
    3 fallo summary

Env vars clave:
    GROBID_SERVER_URL (default http://localhost:8070)
    GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_GENERATIVE_AI_API_KEY
    LEGACY_OUTPUT=1   (si se desea escribir también en output/ presummary.json, summary.json)
"""
from __future__ import annotations
import argparse, sys, json, os, pathlib, subprocess, hashlib, time, re

# Importamos la nueva función de creación de carpeta summary_and_content
from .paper_summary import build_summary_and_content  # type: ignore

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]  # deepread/
BACKEND_DIR = REPO_ROOT / 'backend' / 'summary'
OUTPUT_DIR = REPO_ROOT / 'output'
LEGACY_OUTPUT = os.environ.get('LEGACY_OUTPUT') == '1'

# Global index path (sessions.index.json) stored at repo root for simplicity
GLOBAL_INDEX_PATH = REPO_ROOT / 'sessions.index.json'

def _slugify(text: str, fallback: str = 'paper') -> str:
    t = text.lower()
    t = re.sub(r'[^a-z0-9\s-]+', '', t)
    t = re.sub(r'\s+', '-', t).strip('-')
    return t or fallback

def _calc_pdf_hash(path: pathlib.Path, limit_mb: int = 4) -> str:
    """Hash first N MB for duplicate detection without reading entire huge file."""
    h = hashlib.sha256()
    chunk_size = 1024 * 1024
    remaining = limit_mb * chunk_size
    with path.open('rb') as f:
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()[:16]

def _load_json(path: pathlib.Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}

def _write_json(path: pathlib.Path, obj: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def _update_global_index(meta: dict):
    idx = _load_json(GLOBAL_INDEX_PATH) or {}
    sessions = idx.get('sessions') or []
    # Replace or append by slug
    sessions = [s for s in sessions if s.get('slug') != meta.get('slug')]
    sessions.append({
        'slug': meta.get('slug'),
        'title': meta.get('title'),
        'created_at': meta.get('created_at'),
        'updated_at': meta.get('updated_at'),
        'status': meta.get('status'),
        'equations_kept': meta.get('metrics', {}).get('final_count'),
        'figures': meta.get('metrics', {}).get('figures_extracted')
    })
    idx['sessions'] = sessions
    _write_json(GLOBAL_INDEX_PATH, idx)


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out_lines = []
    while True:
        line = proc.stdout.readline()  # type: ignore
        if not line and proc.poll() is not None:
            break
        if line:
            out_lines.append(line)
    return proc.returncode or 0, ''.join(out_lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdf', help='Ruta al PDF a procesar')
    ap.add_argument('--model', default='gemini-2.0-flash', help='Modelo LLM para summary')
    ap.add_argument('--paper-id', help='Identificador/carpeta del paper (si no se pasa usa stem del PDF)')
    ap.add_argument('--base-dir', default='processed_grobid_pdfs', help='Directorio base donde viven las carpetas de cada paper')
    ap.add_argument('--overwrite', action='store_true', help='Regenerar summary e imágenes aunque existan')
    ap.add_argument('--legacy-session', action='store_true', help='Además generar estructura legacy chatsession_ para compatibilidad')
    ap.add_argument('--keep-existing-presummary', action='store_true', help='(legacy) Reutilizar presummary existente en sesión')
    ap.add_argument('--no-summary', action='store_true', help='Solo ejecutar etapa GROBID (legacy)')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--include-paths', action='store_true', help='(legacy) Incluir rutas detalladas en JSON de salida')
    ap.add_argument('--session-slug', help='(legacy) Forzar slug de sesión')
    ap.add_argument('--session-root', help='(legacy) Raíz de sesiones')
    args = ap.parse_args()

    pdf_path = pathlib.Path(args.pdf)
    if not pdf_path.exists():
        print(json.dumps({'error': 'pdf_not_found', 'path': str(pdf_path)}))
        return 1

    pdf_hash = _calc_pdf_hash(pdf_path)

    # NUEVO FLUJO PRINCIPAL: generar summary_and_content primero
    try:
        sac_result = build_summary_and_content(
            pdf_path=pdf_path,
            base_dir=pathlib.Path(args.base_dir),
            paper_id=args.paper_id,
            overwrite=args.overwrite,
            model=args.model
        )
    except Exception as e:
        print(json.dumps({'error': 'summary_and_content_failed', 'message': str(e)}))
        return 3

    # Si no se pidió legacy-session, devolvemos resultado directo y salimos
    if not args.legacy_session:
        print(json.dumps({
            'status': 'ok',
            'mode': 'summary_and_content',
            **sac_result
        }, ensure_ascii=False, indent=2))
        return 0

    # ---------------- LEGACY SESSION MODE (opcional) ----------------
    session_root_base = pathlib.Path(args.session_root or os.environ.get('SESSION_ROOT_DIR') or REPO_ROOT)
    session_root_base.mkdir(parents=True, exist_ok=True)
    preliminary_slug = args.session_slug or _slugify(pdf_path.stem)
    if not args.session_slug:
        preliminary_slug = f"{preliminary_slug}-{pdf_hash[:6]}"
    session_dir = session_root_base / f"chatsession_{preliminary_slug}_"
    session_dir.mkdir(parents=True, exist_ok=True)
    source_dir = session_dir / 'source'; pres_dir = session_dir / 'presummary'; summ_dir = session_dir / 'summary'; logs_dir = session_dir / 'logs'
    for d in (source_dir, pres_dir, summ_dir, logs_dir): d.mkdir(parents=True, exist_ok=True)
    target_pdf_path = source_dir / 'original.pdf'
    if not target_pdf_path.exists():
        try: target_pdf_path.write_bytes(pdf_path.read_bytes())
        except Exception as e:
            print(json.dumps({'error': 'copy_pdf_failed', 'message': str(e)})); return 1

    # LEGACY: reconstruimos presummary y summary desde artefactos recién creados en summary_and_content
    sac_dir = pathlib.Path(sac_result['summary_json']).parent
    # presummary (legacy presummary.json) = content_json renombrado
    presummary_session_path = pres_dir / 'presummary.json'
    try:
        presummary_session_path.write_text(
            pathlib.Path(sac_result['content_json']).read_text(encoding='utf-8'),
            encoding='utf-8')
    except Exception as e:
        print(json.dumps({'error': 'legacy_presummary_copy_failed', 'message': str(e)})); return 2
    # summary copy
    session_summary_path = summ_dir / 'summary.json'
    try:
        session_summary_path.write_text(
            pathlib.Path(sac_result['summary_json']).read_text(encoding='utf-8'),
            encoding='utf-8')
    except Exception as e:
        print(json.dumps({'error': 'legacy_summary_copy_failed', 'message': str(e)})); return 3
    # Simple logs stub
    (logs_dir / 'runsummary.log').write_text('legacy session generated from summary_and_content pipeline', encoding='utf-8')

    # Load summary meta & compute session meta.json
    summary_obj = _load_json(session_summary_path)
    summary_meta = summary_obj.get('_meta', {}) if isinstance(summary_obj, dict) else {}
    # Equation metrics from summary
    eq_metrics = summary_meta.get('equation_metrics', {})

    created_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    # If we can extract paper title from summary meta, refine slug (no rename to keep reproducibility)
    paper_title = summary_meta.get('paper_title') or summary_meta.get('paper_id') or pdf_path.stem
    session_meta = {
        'slug': preliminary_slug,
        'title': paper_title,
        'created_at': created_at,
        'updated_at': created_at,
        'status': 'completed',
        'pipeline': {
            'llm_provider': 'gemini',
            'model': summary_meta.get('model'),
            'equation_normalizer_version': '1.0.0'
        },
        'metrics': {
            'equations_detected': eq_metrics.get('original_count'),
            'final_count': eq_metrics.get('final_count'),
            'discarded_count': eq_metrics.get('discarded_count'),
            'figures_extracted': len(summary_meta.get('figures', []) or []),
            'tokens_prompt': None,
            'tokens_completion': None,
            'processing_seconds': None
        },
        'paths': {
            'summary': str(session_summary_path.relative_to(session_dir)),
            'presummary': str(presummary_session_path.relative_to(session_dir)),
            'figures_dir': 'presummary/figures',
            'equations': 'summary/summary.json'  # (equations currently embedded)
        },
        'versions': {
            'session': 1,
            'reprocess_of': None
        },
        'pdf_hash': pdf_hash
    }
    _write_json(session_dir / 'meta.json', session_meta)
    _update_global_index(session_meta)

    # Extract cost & token usage if present
    token_usage = summary_meta.get('token_usage', {})
    cost_meta = summary_meta.get('cost', {})
    # Minimal result always returned
    result = {
        'status': 'ok',
        'slug': preliminary_slug,
        'word_count': summary_meta.get('word_count'),
        'equations_kept': len(summary_meta.get('equations', []) or []),
        'figures_kept': len(summary_meta.get('figures', []) or []),
        'model': summary_meta.get('model'),
        'token_usage': token_usage,
        'cost': cost_meta
    }
    # Only include detailed paths if explicitly requested
    if args.include_paths:
        result.update({
            'session_dir': str(session_dir),
            'summary_file': str(session_summary_path),
            'presummary_file': str(presummary_session_path),
            'logs_file': str((logs_dir / 'runsummary.log'))
        })
    # Devolvemos unión de ambas salidas
    result.update({'summary_and_content': sac_result, 'mode': 'legacy+summary_and_content'})
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    sys.exit(main())
