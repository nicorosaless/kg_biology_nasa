from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import json

from .utils import save_jsonl, get_phase_dir

import importlib
import importlib.util

def _ensure_spacy_model(name: str):
    import spacy  # type: ignore
    try:
        return spacy.load(name)
    except OSError:
        # intentar descargar si está permitido
        from spacy.cli import download  # type: ignore
        download(name)
        return spacy.load(name)


def load_sections(base_dir: Path, pmcid: str) -> List[Dict[str, Any]]:
    phase1_dir = get_phase_dir(base_dir, pmcid, 1)
    path = phase1_dir / 'sections.json'
    if not path.exists():
        raise FileNotFoundError('Run phase1 before phase2 (missing sections.json)')
    return json.loads(path.read_text(encoding='utf-8'))


def sentence_segment(sections: List[Dict[str, Any]], model_name: str = 'en_core_web_sm') -> List[Dict[str, Any]]:
    try:
        spacy_spec = importlib.util.find_spec('spacy')
        if spacy_spec is None:
            raise RuntimeError('spaCy no instalado en el entorno actual')
        nlp = _ensure_spacy_model(model_name)
    except Exception as e:
        raise RuntimeError(f'No se pudo cargar el modelo spaCy {model_name}: {e}')

    sentences: List[Dict[str, Any]] = []
    sid = 0
    for sec in sections:
        sec_text = sec['text']
        doc = nlp(sec_text)
        base_global = sec['char_start_global']
        for sent in doc.sents:
            sent_text = sent.text.strip()
            if not sent_text:
                continue
            rel_start = sent.start_char
            rel_end = sent.end_char
            sentences.append({
                'sid': sid,
                'section_index': sec['section_index'],
                'section_heading': sec['heading'],
                'text': sent_text,
                'char_start_section': rel_start,
                'char_end_section': rel_end,
                'char_start_global': base_global + rel_start,
                'char_end_global': base_global + rel_end
            })
            sid += 1
    return sentences


def run(base_dir: Path, pmcid: str):
    sections = load_sections(base_dir, pmcid)
    sentences = sentence_segment(sections)
    out_dir = get_phase_dir(base_dir, pmcid, 2)
    save_jsonl(sentences, out_dir / 'sentences.jsonl')
    return {'sentences': len(sentences)}

if __name__ == '__main__':  # pragma: no cover
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--pmcid', required=True)
    args = p.parse_args()
    print(run(Path(args.base), args.pmcid))
