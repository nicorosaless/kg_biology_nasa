#!/usr/bin/env python3
"""Convenience CLI: PDF -> GROBID (presummary) -> LLM summary following session layout.

Usage:
    python backend/summary/runsummary.py path/to/paper.pdf [--model gemini-2.0-flash]

Session-oriented outputs (new structure):
    chatsession_<slug>_/meta.json
    chatsession_<slug>_/source/original.pdf
    chatsession_<slug>_/presummary/presummary.json
    chatsession_<slug>_/summary/summary.json
    chatsession_<slug>_/summary/prompt.txt
    chatsession_<slug>_/summary/llm_raw_response.txt (if debug enabled later)
    (Legacy optional) output/presummary.json & output/summary.json if LEGACY_OUTPUT=1

Exit codes:
    0 success
    1 argument / file errors
    2 grobid stage failed
    3 summary stage failed

Environment:
 - GROBID server: $GROBID_SERVER_URL (default http://localhost:8070)
 - Gemini key: GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_GENERATIVE_AI_API_KEY
 - LEGACY_OUTPUT=1  -> también escribe artefactos en output/
 - SESSION_ROOT_DIR  -> raíz (por defecto repo root)
"""
from __future__ import annotations
import argparse, sys, json, os, pathlib, subprocess, shlex, hashlib, time, re

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
    ap.add_argument('pdf', help='Path to PDF file to process')
    ap.add_argument('--model', default='gemini-2.0-flash', help='LLM model name for summary')
    ap.add_argument('--keep-existing-presummary', action='store_true', help='Si existe presummary previo dentro de la sesión, lo reutiliza')
    ap.add_argument('--no-summary', action='store_true', help='Only run grobid stage')
    ap.add_argument('--verbose', action='store_true', help='Print underlying tool logs')
    ap.add_argument('--session-slug', help='Forzar slug de sesión (opcional)')
    ap.add_argument('--session-root', help='Raíz donde crear sesiones (por defecto repo root)')
    ap.add_argument('--include-paths', action='store_true', help='Incluir rutas detalladas en la salida JSON (summary_dir, logs, etc.)')
    args = ap.parse_args()

    pdf_path = pathlib.Path(args.pdf)
    if not pdf_path.exists():
        print(json.dumps({'error': 'pdf_not_found', 'path': str(pdf_path)}))
        return 1

    # Prepare session root
    session_root_base = pathlib.Path(args.session_root or os.environ.get('SESSION_ROOT_DIR') or REPO_ROOT)
    session_root_base.mkdir(parents=True, exist_ok=True)

    # For slug we may inspect title after grobid, but we need a path early. Use filename + hash stub first.
    preliminary_slug = args.session_slug or _slugify(pdf_path.stem)
    pdf_hash = _calc_pdf_hash(pdf_path)
    if not args.session_slug:
        # Add short hash to avoid collisions
        preliminary_slug = f"{preliminary_slug}-{pdf_hash[:6]}"
    session_dir = session_root_base / f"chatsession_{preliminary_slug}_"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Subdirs
    source_dir = session_dir / 'source'
    pres_dir = session_dir / 'presummary'
    summ_dir = session_dir / 'summary'
    logs_dir = session_dir / 'logs'
    for d in (source_dir, pres_dir, summ_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Copy PDF (avoid duplicating if same inode - simple check by name existence)
    target_pdf_path = source_dir / 'original.pdf'
    if not target_pdf_path.exists():
        try:
            target_pdf_path.write_bytes(pdf_path.read_bytes())
        except Exception as e:
            print(json.dumps({'error': 'copy_pdf_failed', 'message': str(e)}))
            return 1

    # Legacy output directory (optional)
    if LEGACY_OUTPUT:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    presummary_session_path = pres_dir / 'presummary.json'
    legacy_pres_path = OUTPUT_DIR / 'presummary.json'

    # Stage 1: GROBID extraction (only if not keeping existing)
    if presummary_session_path.exists() and args.keep_existing_presummary:
        if args.verbose:
            print('[runsummary] Reutilizando presummary existente en sesión')
    else:
        # Run grobid script (writes legacy output/presummary.json). We'll then copy into session.
        if legacy_pres_path.exists():
            try: legacy_pres_path.unlink()
            except OSError: pass
        grobid_cmd = [sys.executable, str(BACKEND_DIR / 'grobid.py'), str(pdf_path)]
        code, out = _run(grobid_cmd)
        (logs_dir / 'runsummary.log').write_text(out[-20_000:], encoding='utf-8')
        if args.verbose:
            print(out)
        if code != 0 or not legacy_pres_path.exists():
            print(json.dumps({'error': 'grobid_failed', 'exit_code': code, 'stdout': out[-4000:]}))
            return 2
        # Copy into session
        try:
            presummary_session_path.write_text(legacy_pres_path.read_text(encoding='utf-8'), encoding='utf-8')
        except Exception as e:
            print(json.dumps({'error': 'presummary_copy_failed', 'message': str(e)}))
            return 2

    if args.no_summary:
        print(json.dumps({'status': 'grobid_done', 'presummary': str(presummary_session_path), 'session': str(session_dir)}))
        return 0

    # Stage 2: LLM summary
    legacy_sum_path = OUTPUT_DIR / 'summary.json'
    if legacy_sum_path.exists():
        try: legacy_sum_path.unlink()
        except OSError: pass
    # Prepare prompt/raw file paths inside session structure
    prompt_file = summ_dir / 'prompt.txt'
    raw_file = summ_dir / 'llm_raw_response.txt'
    summary_cmd = [
        sys.executable, str(BACKEND_DIR / 'summary.py'),
        '--model', args.model,
        '--emit-prompt-file', str(prompt_file),
        '--emit-raw-file', str(raw_file)
    ]
    code, out = _run(summary_cmd)
    # Append summary stage logs
    with (logs_dir / 'runsummary.log').open('a', encoding='utf-8') as lf:
        lf.write('\n--- SUMMARY STAGE ---\n')
        lf.write(out[-20_000:])
    if args.verbose:
        print(out)
    if code != 0 or not legacy_sum_path.exists():
        print(json.dumps({'error': 'summary_failed', 'exit_code': code, 'stdout': out[-4000:]}))
        return 3
    # Copy summary into session
    session_summary_path = summ_dir / 'summary.json'
    try:
        session_summary_path.write_text(legacy_sum_path.read_text(encoding='utf-8'), encoding='utf-8')
    except Exception as e:
        print(json.dumps({'error': 'summary_copy_failed', 'message': str(e)}))
        return 3

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
            'prompt_file': str(prompt_file),
            'raw_response_file': str(raw_file),
            'logs_file': str((logs_dir / 'runsummary.log'))
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    sys.exit(main())
