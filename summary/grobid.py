from grobid_client.grobid_client import GrobidClient  # type: ignore
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
import json
import logging
import os
from typing import Optional, Dict, Any, List

"""Proceso mínimo: PDF -> TEI (GROBID) -> JSON + imágenes.
Silencio salvo errores (JSON a stdout). Código reducido para legibilidad."""

try:
    from parse_grobid import (
        save_content_json,
    )  # when executed from package context
    from extract_images import extract_pdf_images
    from crop_figures import crop_missing_figures
except ImportError:
    from backend.summary.parse_grobid import (
        save_content_json,
    )  # fallback when run from project root
    from backend.summary.extract_images import extract_pdf_images
    from backend.summary.crop_figures import crop_missing_figures

NS = { 'tei': 'http://www.tei-c.org/ns/1.0' }

def _error(msg: str, **extra):
    payload = {"error": msg}
    if extra:
        payload.update(extra)
    print(json.dumps(payload, ensure_ascii=False))
    return None

def _remove_obsolete_full_json(out_dir: Path, stem: str):
    for p in out_dir.glob(f"{stem}.grobid.full.json"):
        try: p.unlink()
        except OSError: pass

def _validate_content(content: Dict[str, Any]) -> Dict[str, Any]:
    sections = content.get('sections', [])
    figures = content.get('figures', {})
    equations = content.get('equations', {})
    global_orders, fig_blocks, eq_blocks = [], set(), set()
    for sec in sections:
        for b in sec.get('blocks', []):
            if 'global_order' in b: global_orders.append(b['global_order'])
            if b.get('type') == 'figure' and b.get('id'): fig_blocks.add(b['id'])
            if b.get('type') == 'equation' and b.get('id'): eq_blocks.add(b['id'])
    missing_fig = [k for k in figures if k not in fig_blocks]
    missing_eq = [k for k in equations if k not in eq_blocks]
    contiguous = sorted(global_orders) == list(range(len(global_orders)))
    eq_loc_missing, eq_bbox_missing = [], []
    for k, meta in equations.items():
        if 'section_index' not in meta or 'block_index' not in meta: eq_loc_missing.append(k)
        if meta.get('coords_raw') and not meta.get('bbox'): eq_bbox_missing.append(k)
    return {
        'figure_ids_total': len(figures),
        'equation_ids_total': len(equations),
        'figure_block_ids': len(fig_blocks),
        'equation_block_ids': len(eq_blocks),
        'missing_figure_block_refs': missing_fig,
        'missing_equation_block_refs': missing_eq,
        'global_order_contiguous': contiguous,
        'block_count': sum(len(s.get('blocks', [])) for s in sections),
        'equations_missing_loc': eq_loc_missing,
        'equations_missing_bbox_expected': eq_bbox_missing
    }

def test_grobid_output(pdf_path: Optional[str] = None, server_url: Optional[str] = None):
    logging.getLogger('grobid_client.grobid_client').setLevel(logging.ERROR)
    base_dir = Path(__file__).parent.parent.parent
    if pdf_path is None:
        pdf_path = str(base_dir / 'aiayn.pdf')
    pdf_path_p = Path(pdf_path)
    if not pdf_path_p.exists():
        return _error('pdf_not_found', path=str(pdf_path_p))
    server_url = server_url or os.environ.get('GROBID_SERVER_URL', 'http://localhost:8070')
    try:
        client = GrobidClient(grobid_server=server_url, check_server=False)
        is_up, _ = client.ping()
        if not is_up:
            return _error('grobid_unavailable', server=server_url)
        _, status, response = client.process_pdf(
            pdf_file=str(pdf_path_p),
            service='processFulltextDocument',
            generateIDs=False,
            consolidate_header=False,
            consolidate_citations=False,
            include_raw_citations=True,
            include_raw_affiliations=True,
            tei_coordinates=True,
            segment_sentences=True
        )
        if status != 200 or not response or not response.startswith('<'):
            return _error('bad_response', status=status)
        root = ET.fromstring(response)
        title_elem = root.find('.//tei:titleStmt/tei:title', NS)
        title = ''.join(title_elem.itertext()).strip() if title_elem is not None else ''
        abstract_elem = root.find('.//tei:profileDesc/tei:abstract', NS)
        abstract = ''.join(abstract_elem.itertext()).strip() if abstract_elem is not None else ''
        out_dir = base_dir / 'output' / 'preprocess'
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = pdf_path_p.stem
        _remove_obsolete_full_json(out_dir, stem)
        tmp_path = save_content_json(pdf_path_p, response)
        content_obj = json.loads(tmp_path.read_text(encoding='utf-8'))
        content_obj['metadata']['title'] = title or content_obj['metadata'].get('title', '')
        content_obj['metadata']['abstract'] = abstract or content_obj['metadata'].get('abstract', '')
        img_out_dir = out_dir / 'images' / pdf_path_p.stem
        if img_out_dir.exists():
            for old in img_out_dir.glob('fig_*.*'):
                try:
                    old.unlink()
                except OSError:
                    pass
        images = extract_pdf_images(pdf_path_p, img_out_dir)
        for img in images:
            fig_key = f'fig_{img.fig_index}'
            if fig_key in content_obj.get('figures', {}):
                content_obj['figures'][fig_key]['image_path'] = str(img.path)
            if fig_key in content_obj.get('tables', {}):
                content_obj['tables'][fig_key]['image_path'] = str(img.path)
        cropped = crop_missing_figures(pdf_path_p, content_obj, img_out_dir)
        pure_figs = content_obj.get('figures', {})
        tables = content_obj.get('tables', {})
        fig_mapped = sum(1 for v in pure_figs.values() if 'image_path' in v)
        table_mapped = sum(1 for v in tables.values() if 'image_path' in v)
        synthetic_total = sum(1 for v in pure_figs.values() if v.get('synthetic'))
        original_total = sum(1 for v in pure_figs.values() if not v.get('synthetic'))
        extracted_stats = {
            'extracted_images': len(images),
            'figure_images_mapped': fig_mapped,
            'table_images_mapped': table_mapped,
            'cropped_images': len(cropped),
            'figures_total_all': len(pure_figs) + len(tables),
            'figures_total_pure': len(pure_figs),
            'figures_total_original': original_total,
            'figures_total_synthetic': synthetic_total,
            'tables_total': len(tables),
            'figures_with_image_pure': fig_mapped,
            'tables_with_image': table_mapped,
            'figures_missing_image_pure': len(pure_figs) - fig_mapped,
            'tables_missing_image': len(tables) - table_mapped,
        }
        content_obj['stats']['image_extraction'] = extracted_stats
        content_obj['stats'].update({
            'figures_total_all': extracted_stats['figures_total_all'],
            'figures_total_pure': extracted_stats['figures_total_pure'],
            'figures_total_original': extracted_stats['figures_total_original'],
            'figures_total_synthetic': extracted_stats['figures_total_synthetic'],
            'tables_total': extracted_stats['tables_total'],
            'figures_with_image_pure': extracted_stats['figures_with_image_pure'],
            'tables_with_image': extracted_stats['tables_with_image'],
        })
        validation = _validate_content(content_obj)
        content_obj['stats']['validation'] = validation
        output_path = out_dir / f"{stem}.grobid.content.json"
        serialized = json.dumps(content_obj, ensure_ascii=False, indent=2)
        output_path.write_text(serialized, encoding='utf-8')
        # Also write canonical presummary.json (requested: presummary == original grobid.content.json)
        try:
            presummary_path = Path(__file__).parent.parent.parent / 'output' / 'presummary.json'
            presummary_path.parent.mkdir(parents=True, exist_ok=True)
            presummary_path.write_text(serialized, encoding='utf-8')
        except Exception:
            pass  # non-fatal
        if tmp_path != output_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return output_path
    except Exception as e:
        return _error('exception', message=str(e))

if __name__ == '__main__':
    # CLI simple: test_grobid.py [PDF_PATH] [SERVER_URL]
    pdf_arg = sys.argv[1] if len(sys.argv) > 1 else None
    server_arg = sys.argv[2] if len(sys.argv) > 2 else None
    res = test_grobid_output(pdf_arg, server_arg)
    # Exit code semantics: 0 si OK, 1 si error (detectado por no devolver Path)
    if res is None:
        sys.exit(1)
    sys.exit(0)