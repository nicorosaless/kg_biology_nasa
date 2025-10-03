"""Utilities to extract plain text and structured snippets from GROBID *.grobid.content.json files.

We expect each JSON to follow the schema produced by parse_grobid.save_content_json.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict, Any, Iterable

SECTION_MIN_WORDS = 5

def load_content_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))

def iter_section_text(content: Dict[str, Any]) -> Iterable[str]:
    for sec in content.get('sections', []):
        txt = sec.get('text') or ''
        if not txt:
            continue
        if len(txt.split()) < SECTION_MIN_WORDS:
            continue
        yield txt.strip()

def concatenate_sections(content: Dict[str, Any], joiner: str = '\n\n') -> str:
    return joiner.join(iter_section_text(content))

def extract_metadata_summary(content: Dict[str, Any]) -> str:
    meta = content.get('metadata', {})
    title = meta.get('title', '')
    abstract = meta.get('abstract', '')
    parts = [p for p in [title.strip(), abstract.strip()] if p]
    return '\n'.join(parts)

__all__ = [
    'load_content_json', 'iter_section_text', 'concatenate_sections', 'extract_metadata_summary'
]
