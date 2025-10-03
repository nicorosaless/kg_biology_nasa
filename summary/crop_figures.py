from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import re
import fitz  # PyMuPDF


def crop_missing_figures(pdf_path: Path, content: Dict[str, Any], out_dir: Path,
                          zoom: float = 2.0, min_width: int = 20, min_height: int = 20) -> List[str]:
    """Generate cropped images for figures (and tables) that still lack an image_path.

    Uses the 'bbox' field produced in parse_grobid (page, x1,y1,x2,y2). Coordinates are
    in PDF units. We apply a zoom for better resolution. Returns list of newly created image paths.
    """
    created: List[str] = []
    if not pdf_path.exists():
        return created
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    def _emit(fig_key: str, meta: Dict[str, Any]):
        bbox = meta.get('bbox')
        if not bbox:  # no coords
            return
        if 'image_path' in meta:  # already has
            return
        page_index = bbox.get('page') - 1
        if page_index < 0 or page_index >= len(doc):
            return
        page = doc[page_index]
        x1, y1, x2, y2 = bbox['x1'], bbox['y1'], bbox['x2'], bbox['y2']
        if x2 - x1 < min_width or y2 - y1 < min_height:
            return
        rect = fitz.Rect(x1, y1, x2, y2)
        # Render only the region
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, clip=rect, alpha=False)
        if pix.width < min_width or pix.height < min_height:
            return
        img_path = out_dir / f"{fig_key}.crop.png"
        pix.save(str(img_path))
        meta['image_path'] = str(img_path)
        meta['image_cropped'] = True
        meta['image_zoom'] = zoom
        created.append(str(img_path))
    figures = content.get('figures', {})
    tables = content.get('tables', {})
    for k, v in figures.items():
        _emit(k, v)
    for k, v in tables.items():
        _emit(k, v)
    # Heuristic synthetic cropping: if synthetic and no bbox, approximate from its paragraph text lines not available
    # (Skipped unless future coordinate derivation added.)
    return created

__all__ = ['crop_missing_figures']
