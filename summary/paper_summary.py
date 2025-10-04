#!/usr/bin/env python3
"""Pipeline simplificado para generar la carpeta summary_and_content de un paper.

Estructura solicitada (por paper, ej: PMC11988870):

<base>/<paper_id>/
  graph/                 (YA existente del pipeline KG)
  summary_and_content/
    <paper_id>.content.json      # (antes: *.grobid.content.json)
    summary.json                 # resumen LLM enriquecido
    figures/                     # imágenes extraídas (fig_1.png ...)

Uso CLI:
  python -m summary.paper_summary --pdf SB_publications/pdfs/PMC11988870.pdf \
      --paper-id PMC11988870 --base-dir processed_grobid_pdfs

Si ya existe el archivo <paper_id>.grobid.content.json en la ruta GROBID procesada
(lo produce grobid.py) lo reutiliza. Si no existe, invoca grobid.test_grobid_output
para generarlo (requiere GROBID corriendo y dependencias).

Variables de entorno:
  GROBID_SERVER_URL  (por defecto http://localhost:8070)
  GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_GENERATIVE_AI_API_KEY (para resumen)

Salida JSON (stdout) mínima:
  {
    "status": "ok",
    "content_json": ".../summary_and_content/PMCxxxx.content.json",
    "summary_json": ".../summary_and_content/summary.json",
    "figures_dir": ".../summary_and_content/figures",
    "figure_count": N,
    "word_count": M
  }

Notas:
 - No reescribe summary.json si existe y --overwrite no se pasa.
 - Se elimina la carpeta intermedia grobid_raw: el JSON base se genera (o reutiliza) directamente como <paper_id>.content.json.
 - Actualiza en summary.json los paths de figuras relativo a figures/ si es posible.
"""
from __future__ import annotations
import argparse, json, os, shutil, pathlib, sys
from typing import Any, Dict

# Reutilizamos funciones de los módulos existentes
from . import grobid as grobid_mod  # type: ignore
from . import summary as summary_mod  # type: ignore
from .extract_images import extract_pdf_images  # type: ignore
from .crop_figures import crop_missing_figures  # type: ignore

DEF_SERVER = os.environ.get('GROBID_SERVER_URL', 'http://localhost:8070')


def _load_json(p: pathlib.Path) -> Dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return {}


def ensure_content_json(pdf_path: pathlib.Path, target_content_path: pathlib.Path, overwrite: bool) -> pathlib.Path:
    """Asegura que exista <paper_id>.content.json en summary_and_content.
    Reglas:
      1. Si existe y no overwrite: reutiliza.
      2. Si no existe o overwrite: invoca GROBID para generar un *.grobid.content.json temporal
         y lo transforma / copia como <paper_id>.content.json.
    """
    if target_content_path.exists() and not overwrite:
        return target_content_path
    res_path = grobid_mod.test_grobid_output(str(pdf_path))
    if not res_path or not isinstance(res_path, pathlib.Path):
        raise RuntimeError("grobid_generation_failed")
    # Leer y volcar directo (podríamos renombrar, pero preservamos formato estable)
    try:
        data = json.loads(res_path.read_text(encoding='utf-8'))
    except Exception as e:
        raise RuntimeError(f"invalid_grobid_json: {e}")
    target_content_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return target_content_path


def build_summary_and_content(pdf_path: pathlib.Path, base_dir: pathlib.Path, paper_id: str | None = None, overwrite: bool = False, model: str = 'gemini-2.0-flash') -> Dict[str, Any]:
    paper_id = paper_id or pdf_path.stem
    paper_root = base_dir / paper_id
    # Directorio target summary_and_content
    sac_dir = paper_root / 'summary_and_content'
    figures_dir = sac_dir / 'figures'
    sac_dir.mkdir(parents=True, exist_ok=True)

    # 1. content JSON (directo en summary_and_content)
    target_content_path = sac_dir / f'{paper_id}.content.json'
    ensure_content_json(pdf_path, target_content_path, overwrite)
    raw_content = _load_json(target_content_path)
    if not raw_content:
        raise RuntimeError('empty_content_json')

    # 2. Extraer figuras (si no existen ya) -> figures/
    #   Intentamos reutilizar rutas existentes (image_path) copiando los archivos; si no, re-extraemos del PDF
    figures_dir.mkdir(parents=True, exist_ok=True)
    existing_images = list(figures_dir.glob('fig_*.*'))
    need_extract = overwrite or len(existing_images) == 0
    figure_map = raw_content.get('figures', {}) or {}
    copied = 0
    if need_extract:
        # Intentar copiar las image_path referenciadas
        for fid, meta in figure_map.items():
            img_path = meta.get('image_path')
            if not img_path:
                continue
            src = pathlib.Path(img_path)
            if not src.exists():
                continue
            # Normalizamos extensión
            ext = src.suffix.lower() or '.png'
            dst = figures_dir / f'{fid}{ext}'
            try:
                shutil.copyfile(src, dst)
                meta['image_path'] = str(dst.relative_to(sac_dir))  # path relativo final
                copied += 1
            except Exception:
                pass
        # Si no copiamos nada o faltan figuras, extraemos imágenes del PDF
        if copied == 0:
            extracted = extract_pdf_images(pdf_path, figures_dir)
            for img in extracted:
                fid = f'fig_{img.fig_index}'
                if fid in figure_map:
                    # Ajustamos path relativo
                    rel = figures_dir / img.path.name
                    figure_map[fid]['image_path'] = str(rel.relative_to(sac_dir))
        # Intento de crop para figuras faltantes
        crop_missing_figures(pdf_path, raw_content, figures_dir)
    else:
        # Reutilizar paths existentes ya presentes en figures_dir
        for fid, meta in figure_map.items():
            # Buscar archivo que empiece por fid
            matches = list(figures_dir.glob(f'{fid}.*'))
            if matches:
                meta['image_path'] = str(matches[0].relative_to(sac_dir))

    # 3. Generar summary.json (usa summary.summarize_content)
    summary_path = sac_dir / 'summary.json'
    if overwrite or not summary_path.exists():
        try:
            summary_obj = summary_mod.summarize_content(raw_content, model_name=model)
        except Exception as e:
            raise RuntimeError(f'summary_generation_failed: {e}')
        # Ajustar paths de figuras dentro del summary (si hay enriched figs)
        def _adjust_fig_paths(sec: dict):
            if not isinstance(sec, dict):
                return
            figs = sec.get('figures')
            if isinstance(figs, list):
                for f in figs:
                    if isinstance(f, dict) and f.get('id') in figure_map:
                        src_meta = figure_map[f['id']]
                        if 'image_path' in src_meta:
                            f['image_path'] = src_meta['image_path']
        for key in ['intro', 'conclusion']:
            if key in summary_obj:
                _adjust_fig_paths(summary_obj[key])
        if isinstance(summary_obj.get('sections'), list):
            for s in summary_obj['sections']:
                _adjust_fig_paths(s)
        summary_path.write_text(json.dumps(summary_obj, ensure_ascii=False, indent=2), encoding='utf-8')
        word_count = summary_obj.get('_meta', {}).get('word_count')
    else:
        word_count = _load_json(summary_path).get('_meta', {}).get('word_count')

    # Conteo final de figuras con imagen
    figure_count = sum(1 for v in figure_map.values() if v.get('image_path'))

    return {
        'status': 'ok',
        'paper_id': paper_id,
        'content_json': str(target_content_path),
        'summary_json': str(summary_path),
        'figures_dir': str(figures_dir),
        'figure_count': figure_count,
        'word_count': word_count
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True, help='Ruta al PDF del paper')
    ap.add_argument('--paper-id', help='ID/carpeta del paper (si omite usa stem del PDF)')
    ap.add_argument('--base-dir', default='processed_grobid_pdfs', help='Directorio base donde están las carpetas por paper')
    ap.add_argument('--overwrite', action='store_true', help='Recalcular summary e imágenes aunque existan')
    ap.add_argument('--model', default='gemini-2.0-flash')
    args = ap.parse_args()

    pdf_path = pathlib.Path(args.pdf)
    if not pdf_path.exists():
        print(json.dumps({'error': 'pdf_not_found', 'path': str(pdf_path)}))
        return 1

    base_dir = pathlib.Path(args.base_dir)
    try:
        result = build_summary_and_content(pdf_path, base_dir, paper_id=args.paper_id, overwrite=args.overwrite, model=args.model)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(json.dumps({'error': 'pipeline_failed', 'message': str(e)}))
        return 2

if __name__ == '__main__':
    sys.exit(main())
