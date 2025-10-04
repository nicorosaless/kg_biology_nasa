from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Tuple
import json
from collections import defaultdict

from .utils import get_phase_dir, save_jsonl
from . import config
from . import relation_rules as rules

try:
    import spacy
except ImportError:  # pragma: no cover
    spacy = None  # type: ignore

_small_nlp = None  # cached small model

COOC_RULES = rules.COOC_RULES
SYMMETRIC_TYPES = rules.SYMMETRIC_TYPES
VERB_FAMILIES = rules.VERB_FAMILIES


def load_sentences(base_dir: Path, pmcid: str) -> List[Dict[str, Any]]:
    phase2 = get_phase_dir(base_dir, pmcid, 2)
    path = phase2 / 'sentences.jsonl'
    if not path.exists():
        raise FileNotFoundError('Run phase2 before phase4 (missing sentences.jsonl)')
    sents: List[Dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            sents.append(json.loads(line))
    return sents


def load_entities(base_dir: Path, pmcid: str) -> List[Dict[str, Any]]:
    phase3 = get_phase_dir(base_dir, pmcid, 3)
    path = phase3 / 'entities.jsonl'
    if not path.exists():
        raise FileNotFoundError('Run phase3 before phase4 (missing entities.jsonl)')
    ents: List[Dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            ents.append(json.loads(line))
    return ents


def get_small_nlp():
    global _small_nlp
    if _small_nlp is not None:
        return _small_nlp
    if not spacy:
        return None
    try:
        _small_nlp = spacy.load('en_core_web_sm')
    except Exception:  # pragma: no cover
        _small_nlp = None
    return _small_nlp


def index_entities_by_sentence(entities: List[Dict[str, Any]]):
    idx = defaultdict(list)
    for e in entities:
        idx[e['sentence_id']].append(e)
    return idx


def cooccurrence_relations(sentences, sent_entities_idx, start_rid=0) -> Tuple[List[Dict[str, Any]], int]:
    rels: List[Dict[str, Any]] = []
    rid = start_rid
    for sent in sentences:
        sid = sent['sid']
        ents = sent_entities_idx.get(sid, [])
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = ents[i], ents[j]
                at, bt = a.get('node_type'), b.get('node_type')
                if not at or not bt:
                    continue
                rel_type = COOC_RULES.get((at, bt))
                if not rel_type:
                    rev_type = COOC_RULES.get((bt, at))
                    if rev_type:
                        rel_type = rev_type
                        a, b = b, a
                    elif at == 'GENE_PRODUCT' and bt == 'GENE_PRODUCT':
                        rel_type = 'GENE_PRODUCT_INTERACTS_WITH_GENE_PRODUCT'
                    else:
                        continue
                rels.append({
                    'rid': rid,
                    'type': rel_type,
                    'source_eid': a['eid'],
                    'target_eid': b['eid'],
                    'sentence_id': sid,
                    'section_heading': sent['section_heading'],
                    'evidence_span': sent['text'][:240],
                    'method': 'COOC',
                    'trigger': None,
                    'pattern_type': 'COOC'
                })
                rid += 1
    return rels, rid


def verb_pattern_relations(sentences, sent_entities_idx, start_rid=0) -> Tuple[List[Dict[str, Any]], int]:
    nlp = get_small_nlp()
    if not nlp:
        return [], start_rid
    rels: List[Dict[str, Any]] = []
    rid = start_rid
    for sent in sentences:
        sid = sent['sid']
        ents = sent_entities_idx.get(sid, [])
        if len(ents) > config.MAX_ENTITIES_VERB_PATTERN_SENT:
            continue
        doc = nlp(sent['text'])
        verbs = [t for t in doc if t.pos_ == 'VERB']
        for v in verbs:
            lemma = v.lemma_.lower()
            fam = VERB_FAMILIES.get(lemma)
            if not fam:
                continue
            for a in ents:
                for b in ents:
                    if a is b:
                        continue
                    at, bt = a.get('node_type'), b.get('node_type')
                    if not at or not bt:
                        continue
                    rel_type = rules.map_verb_relation(at, bt, fam)
                    if not rel_type:
                        continue
                    rels.append({
                        'rid': rid,
                        'type': rel_type,
                        'source_eid': a['eid'],
                        'target_eid': b['eid'],
                        'sentence_id': sid,
                        'section_heading': sent['section_heading'],
                        'evidence_span': sent['text'][:240],
                        'method': 'VERB',
                        'trigger': lemma,
                        'pattern_type': 'VERB'
                    })
                    rid += 1
    return rels, rid


def run(base_dir: Path, pmcid: str):
    sentences = load_sentences(base_dir, pmcid)
    entities = load_entities(base_dir, pmcid)
    sent_idx = index_entities_by_sentence(entities)
    rels: List[Dict[str, Any]] = []
    cooc, rid_after = cooccurrence_relations(sentences, sent_idx, start_rid=0)
    rels.extend(cooc)
    verb_rels, _ = verb_pattern_relations(sentences, sent_idx, start_rid=rid_after)
    rels.extend(verb_rels)
    out_dir = get_phase_dir(base_dir, pmcid, 4)
    save_jsonl(rels, out_dir / 'relations.jsonl')
    return {'relations': len(rels)}


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--pmcid', required=True)
    a = p.parse_args()
    print(run(Path(a.base), a.pmcid))
