#!/usr/bin/env python3
"""
full_pipeline.py
-----------------
Ejecución unificada: PDF(s) -> summary_and_content -> KG (fases 1-5) -> reporte consolidado.

Uso:
  python full_pipeline.py --pdf SB_publications/pdfs/PMC11988870.pdf \
      --base-dir processed_grobid_pdfs
  
  # Procesar todos los PDFs de una carpeta (máx 5 por defecto)
  python full_pipeline.py --pdf-dir SB_publications/pdfs --limit 5

Salida:
  JSON en stdout con resumen por paper (summary paths + stats KG).

Requisitos previos:
  - Servidor GROBID corriendo (GROBID_SERVER_URL)
  - Variable de API para LLM (p.ej. GEMINI_API_KEY) si se genera summary
  - Estructura repo tal como está (summary/, kg_creator/)

Atajos de latencia:
  - Reusa summary si ya existe y no se pasa --overwrite
  - Reusa fases del KG si ya existen y no se pasa --force-kg

"""
from __future__ import annotations
import argparse, json, sys, pathlib, time, traceback
from typing import List, Dict, Any

# Import funciones internas
from summary.runsummary import build_summary_and_content  # type: ignore
from kg_creator import run as kg_run


def ensure_paper_id(pdf_path: pathlib.Path, provided: str | None) -> str:
    if provided:
        return provided
    stem = pdf_path.stem
    # Acepta que ya venga como PMCxxxxx sino usa stem directo
    return stem


def run_summary_phase(pdf: pathlib.Path, base_dir: pathlib.Path, paper_id: str, overwrite: bool, model: str) -> Dict[str, Any]:
    """Run summary phase with simple caching.

    If summary_and_content/<paper_id>.content.json and summary.json exist and overwrite=False,
    skip regeneration. Returns dict with keys: content_json, summary_json, figures_dir, cached(bool).
    """
    sac_dir = base_dir / paper_id / 'summary_and_content'
    summary_json = sac_dir / 'summary.json'
    content_json = sac_dir / f"{paper_id}.content.json"
    if not overwrite and summary_json.exists() and content_json.exists():
        return {
            'content_json': str(content_json),
            'summary_json': str(summary_json),
            'figures_dir': str(sac_dir / 'figures'),
            'cached': True
        }
    res = build_summary_and_content(
        pdf_path=pdf,
        base_dir=base_dir,
        paper_id=paper_id,
        overwrite=overwrite,
        model=model
    )
    res['cached'] = False
    return res


def run_kg_phases(base_dir: pathlib.Path, paper_id: str, force: bool) -> Dict[str, Any]:
    # Determinar si ya existe phase5/graph_core.json
    phase5_dir = base_dir / paper_id / 'graph' / 'phase5'
    if phase5_dir.exists() and (phase5_dir / 'graph_core.json').exists() and not force:
        return {"status": "cached", "phase5": str(phase5_dir / 'graph_core.json')}
    stats = kg_run.run_phases(base_dir, paper_id, [1,2,3,4,5])
    # stats incluye phase5 -> devolver resumen reducido
    phase5_stats = stats.get('phase5', {})
    return {"status": "built", "stats": phase5_stats, "phase5_dir": str(phase5_dir)}


def collect_reports(base_dir: pathlib.Path, paper_id: str) -> Dict[str, Any]:
    phase5_dir = base_dir / paper_id / 'graph' / 'phase5'
    core_path = phase5_dir / 'graph_core.json'
    section_overview = phase5_dir / 'section_overview.json'
    out: Dict[str, Any] = {"paper_id": paper_id}
    if core_path.exists():
        try:
            core_obj = json.loads(core_path.read_text(encoding='utf-8'))
            out['graph'] = {
                'n_nodes': len(core_obj.get('nodes', [])),
                'n_edges': len(core_obj.get('edges', [])),
                'types': list({n.get('type') for n in core_obj.get('nodes', []) if n.get('type')})[:10]
            }
        except Exception:
            out['graph_error'] = 'failed_to_read_core'
    if section_overview.exists():
        try:
            ov = json.loads(section_overview.read_text(encoding='utf-8'))
            out['sections'] = ov.get('meta', {}).get('total_sections')
        except Exception:
            out['sections'] = None
    return out


def process_pdf(pdf_path: pathlib.Path, args) -> Dict[str, Any]:
    paper_id = ensure_paper_id(pdf_path, args.paper_id)
    result: Dict[str, Any] = {"paper_id": paper_id, "pdf": str(pdf_path)}
    t0_total = time.time()
    summary_time = None
    kg_time = None
    # Summary phase (unless --no-summary)
    if not args.no_summary:
        st0 = time.time()
        try:
            summary_res = run_summary_phase(pdf_path, pathlib.Path(args.base_dir), paper_id, args.overwrite, args.model)
            summary_time = round(time.time() - st0, 2)
            result['summary'] = {
                'content_json': summary_res.get('content_json'),
                'summary_json': summary_res.get('summary_json'),
                'figures_dir': summary_res.get('figures_dir'),
                'cached': summary_res.get('cached', False)
            }
        except Exception as e:
            result['error_summary'] = str(e)
            result['trace'] = traceback.format_exc()
            # If summary fails we stop early because KG depends on content
            result['timing'] = {
                'summary_seconds': summary_time,
                'kg_seconds': None,
                'total_seconds': round(time.time() - t0_total, 2)
            }
            return result

    # KG phase (unless --no-kg)
    if not args.no_kg:
        kt0 = time.time()
        try:
            kg_res = run_kg_phases(pathlib.Path(args.base_dir), paper_id, args.force_kg)
            kg_time = round(time.time() - kt0, 2)
            result['kg'] = kg_res
        except Exception as e:
            result['error_kg'] = str(e)
            result['trace_kg'] = traceback.format_exc()
    total_time = round(time.time() - t0_total, 2)
    result['timing'] = {
        'summary_seconds': summary_time,
        'kg_seconds': kg_time,
        'total_seconds': total_time
    }
    result.update(collect_reports(pathlib.Path(args.base_dir), paper_id))
    return result


def gather_pdfs(args) -> List[pathlib.Path]:
    if args.pdf:
        return [pathlib.Path(args.pdf)]
    pdf_dir = pathlib.Path(args.pdf_dir)
    if not pdf_dir.exists():
        raise FileNotFoundError(f"PDF dir not found: {pdf_dir}")
    all_pdfs = sorted([p for p in pdf_dir.glob('*.pdf')])
    if args.limit:
        return all_pdfs[:args.limit]
    return all_pdfs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', help='Ruta a un PDF individual')
    ap.add_argument('--pdf-dir', help='Carpeta con PDFs (usa --limit para recorte)')
    ap.add_argument('--limit', type=int, default=5, help='Máx PDFs a procesar de la carpeta')
    ap.add_argument('--paper-id', help='Forzar paper_id (solo si --pdf único)')
    # Default output path moved under backend/ as requerido
    ap.add_argument('--base-dir', default='backend/processed_grobid_pdfs')
    ap.add_argument('--model', default='gemini-2.0-flash')
    ap.add_argument('--overwrite', action='store_true', help='Regenerar summary si ya existe')
    ap.add_argument('--force-kg', action='store_true', help='Recalcular fases KG aunque exista phase5')
    ap.add_argument('--no-kg', action='store_true', help='Solo summary')
    ap.add_argument('--no-summary', action='store_true', help='Solo KG (requiere que exista content_json)')
    args = ap.parse_args()

    if not args.pdf and not args.pdf_dir:
        print(json.dumps({'error':'need_pdf_or_pdf_dir'})); return 1
    try:
        pdfs = gather_pdfs(args)
    except Exception as e:
        print(json.dumps({'error':'collect_pdfs_failed','message':str(e)})); return 1

    results = []
    for pdf in pdfs:
        res = process_pdf(pdf, args)
        results.append(res)

    # Aggregate metrics
    def collect_times(key: str):
        vals = [r['timing'][key] for r in results if r.get('timing') and r['timing'].get(key) is not None]
        if not vals:
            return {'avg': None, 'min': None, 'max': None, 'sum': None}
        return {
            'avg': round(sum(vals)/len(vals),2),
            'min': min(vals),
            'max': max(vals),
            'sum': round(sum(vals),2)
        }
    summary_cache_hits = sum(1 for r in results if r.get('summary', {}).get('cached'))
    kg_cache_hits = sum(1 for r in results if r.get('kg', {}).get('status') == 'cached')
    aggregate = {
        'summary_time': collect_times('summary_seconds'),
        'kg_time': collect_times('kg_seconds'),
        'total_time': collect_times('total_seconds'),
        'summary_cache_hits': summary_cache_hits,
        'kg_cache_hits': kg_cache_hits,
        'processed': len(results)
    }

    print(json.dumps({'status':'ok','count': len(results),'aggregate': aggregate,'papers': results}, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
