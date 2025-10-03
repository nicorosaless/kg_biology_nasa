"""Build a lightweight knowledge graph from processed GROBID content JSON files.

Pipeline:
1. Discover *.grobid.content.json under processed_grobid_pdfs/**
2. For each file: load JSON, concatenate section text, extract entities
3. (Optional future) relation extraction; currently adds simple co-occurrence relations within a window
4. Export combined graph to JSON or CSV/TSV for Neo4j import

CLI usage:
python -m kg_creator.build_graph --input processed_grobid_pdfs --out graph.json
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import List, Tuple
from .extract_text import load_content_json, concatenate_sections, extract_metadata_summary
from .entities import EntityAccumulator, extract_entities

COOCCURRENCE_WINDOW = 300  # chars; naive relation creation


def iter_content_files(root: Path):
    for path in root.rglob('*.grobid.content.json'):
        yield path


def build_graph(input_dir: Path) -> dict:
    acc = EntityAccumulator()
    doc_count = 0
    content_files = list(iter_content_files(input_dir))
    if not content_files:
        raise SystemExit(f"[ERROR] No *.grobid.content.json found under {input_dir}")
    for f in content_files:
        doc_id = f.parent.name  # assuming folder name is PMCID
        try:
            content = load_content_json(f)
        except Exception as e:
            print(f"[WARN] Failed to load {f}: {e}")
            continue
        text = extract_metadata_summary(content) + '\n\n' + concatenate_sections(content)
        if not text.strip():
            print(f"[WARN] Empty text for {f}")
            continue
        before_entities = len(acc.entities)
        extract_entities(text, doc_id, acc)
        added_entities = len(acc.entities) - before_entities
        print(f"[INFO] {doc_id}: +{added_entities} entities (total {len(acc.entities)})")
        entities_in_doc = [e for e in acc.entities.values() if e.source == doc_id]
        rel_before = len(acc.relations)
        for i in range(len(entities_in_doc)):
            for j in range(i + 1, len(entities_in_doc)):
                ei, ej = entities_in_doc[i], entities_in_doc[j]
                if ei.type == ej.type:
                    continue
                evidence = f"cooccur:{doc_id}"
                acc.add_relation('COOCCURS_WITH', ei, ej, evidence)
        rel_added = len(acc.relations) - rel_before
        print(f"[INFO] {doc_id}: +{rel_added} relations (total {len(acc.relations)})")
        doc_count += 1
    base = acc.as_dict()
    stats = {
        'documents': doc_count,
        'entities': len(base['entities']),
        'relations': len(base['relations'])
    }
    print(f"[SUMMARY] docs={stats['documents']} entities={stats['entities']} relations={stats['relations']}")
    return {**base, 'stats': stats}


def save_graph(graph: dict, out_path: Path):
    out_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, default=Path('processed_grobid_pdfs'))
    p.add_argument('--out', type=Path, default=Path('graph.json'))
    args = p.parse_args()
    graph = build_graph(args.input)
    save_graph(graph, args.out)
    print(f"Graph saved to {args.out} with {len(graph['entities'])} entities and {len(graph['relations'])} relations")

if __name__ == '__main__':
    main()
