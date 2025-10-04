from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
from .utils import load_content_json, save_json, get_phase_dir

MIN_SECTION_WORDS = 15

NORMALIZE_HEADINGS = {
    'introduction': 'INTRODUCTION',
    'background': 'INTRODUCTION',
    'methods': 'METHODS',
    'materials and methods': 'METHODS',
    'results': 'RESULTS',
    'discussion': 'DISCUSSION',
    'conclusion': 'CONCLUSION',
    'conclusions': 'CONCLUSION',
    'abstract': 'ABSTRACT'
}


def normalize_heading(h: str) -> str:
    key = h.strip().lower()
    return NORMALIZE_HEADINGS.get(key, h.strip())


def filter_sections(content: Dict[str, Any]) -> List[Dict[str, Any]]:
    filtered = []
    cursor = 0  # global char offset acumulado
    for sec in content.get('sections', []):
        raw_text = sec.get('text', '') or ''
        text = raw_text.strip()
        if not text:
            continue
        if len(text.split()) < MIN_SECTION_WORDS:
            cursor += len(raw_text)
            continue
        heading = normalize_heading(sec.get('heading', '').strip() or 'UNLABELED')
        start = cursor + (0 if raw_text.startswith(text) else raw_text.find(text))
        end = start + len(text)
        filtered.append({
            'heading': heading,
            'text': text,
            'section_index': len(filtered),
            'char_start_global': start,
            'char_end_global': end
        })
        cursor += len(raw_text)
    return filtered


def run(base_dir: Path, pmcid: str):
    content = load_content_json(base_dir, pmcid)
    sections = filter_sections(content)
    out_dir = get_phase_dir(base_dir, pmcid, 1)
    save_json(sections, out_dir / 'sections.json')
    return {'sections': len(sections)}

if __name__ == '__main__':  # simple manual test
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--pmcid', required=True)
    args = parser.parse_args()
    stats = run(Path(args.base), args.pmcid)
    print(stats)
