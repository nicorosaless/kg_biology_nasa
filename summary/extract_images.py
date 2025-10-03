"""PDF image extraction utility.

Extracts raster images from a PDF preserving page order, returning a mapping
that can be aligned with GROBID figure order. We assume that figures extracted
by GROBID appear in natural reading order similar to image extraction order.
If there are more extracted images than figures we keep only first N.

Limitations: Without coordinates alignment we cannot guarantee perfect match
when the PDF has decorative logos or repeated icons. Optionally we could filter
small images by area/bytes.
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Tuple
import fitz  # PyMuPDF

class PDFImage:
    def __init__(self, fig_index: int, page: int, path: Path, width: int, height: int, bytes_size: int):
        self.fig_index = fig_index
        self.page = page
        self.path = path
        self.width = width
        self.height = height
        self.bytes_size = bytes_size

    def to_dict(self) -> Dict[str, Any]:
        return {
            'fig_index': self.fig_index,
            'page': self.page,
            'path': str(self.path),
            'width': self.width,
            'height': self.height,
            'bytes': self.bytes_size
        }

def extract_pdf_images(pdf_path: Path, out_dir: Path, max_images: int | None = None,
                       min_width: int = 64, min_height: int = 64, min_bytes: int = 2048) -> List[PDFImage]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    images: List[PDFImage] = []
    counter = 1
    for page_index, page in enumerate(doc):
        img_list = page.get_images(full=True)
        for img_info in img_list:
            xref = img_info[0]
            base = doc.extract_image(xref)
            img_bytes = base.get('image')
            if not img_bytes:
                continue
            width = base.get('width', 0)
            height = base.get('height', 0)
            if width < min_width or height < min_height or len(img_bytes) < min_bytes:
                # Skip very small images (likely icons)
                continue
            ext = base.get('ext', 'png')
            fname = f"fig_{counter}.{ext}"
            img_path = out_dir / fname
            with img_path.open('wb') as f:
                f.write(img_bytes)
            images.append(PDFImage(counter, page_index + 1, img_path, width, height, len(img_bytes)))
            counter += 1
            if max_images and len(images) >= max_images:
                break
        if max_images and len(images) >= max_images:
            break
    return images

__all__ = ['extract_pdf_images', 'PDFImage']
