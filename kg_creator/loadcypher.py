from __future__ import annotations
"""Utility to load phase5 Neo4j CSV exports into a local Neo4j instance.

Assumptions:
- You have run phase5_graph for one or more PMCIDs producing
  processed_grobid_pdfs/<PMCID>/graph/phase5/neo4j/(nodes.csv, relationships.csv)
- Neo4j is running locally (default bolt uri bolt://localhost:7687)
- APOC not required (we reuse single REL label with type property). Optionally you
  can later refactor to dynamic relationship types.

Features:
- Batching insertion
- Optional purge of existing graph
- Idempotent MERGE on nodes
- Optional filtering of very short low-frequency fragments (--min-len) before ingest
- Dry run mode (no writes)

Usage examples:
python -m kg_creator.loadcypher --base processed_grobid_pdfs --pmcid PMC11988870 \
  --user neo4j --password test --purge

Batch size tuning: default 1000.
"""
import argparse
import csv
from pathlib import Path
from typing import List, Dict, Any, Iterable

try:
    from neo4j import GraphDatabase  # type: ignore
except ImportError as e:  # pragma: no cover
    raise SystemExit("neo4j Python driver not installed. Install with: pip install neo4j") from e

NODE_HEADERS = ['id:ID','mention','frequency:int','node_type:LABEL','sections']
REL_HEADERS = [':START_ID',':END_ID','type:TYPE','method','trigger','evidence_span','section_heading','sentence_id:int']


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


def filter_nodes(nodes: List[Dict[str, str]], min_len: int) -> List[Dict[str, str]]:
    if min_len <= 0:
        return nodes
    keep = []
    for n in nodes:
        mention = n.get('mention','')
        freq = int(n.get('frequency:int') or n.get('frequency') or 0)
        if len(mention) < min_len and freq <= 1:
            continue
        keep.append(n)
    return keep


def open_driver(uri: str, user: str, password: str):
    return GraphDatabase.driver(uri, auth=(user, password))


def purge_db(session):
    session.run("MATCH (n) DETACH DELETE n")


def ensure_indexes(session):
    session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:ENTITY) REQUIRE n.id IS UNIQUE")


def chunk_iter(iterable: Iterable[Any], size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def load_nodes(session, nodes: List[Dict[str, str]], batch_size: int, dry: bool=False):
    cypher = (
        "UNWIND $rows AS row MERGE (n:ENTITY {id: row.id}) "
        "SET n.mention = row.mention, n.frequency = row.frequency, "
        "n.node_type = row.node_type, n.sections = row.sections"
    )
    for batch in chunk_iter(({
        'id': n['id:ID'],
        'mention': n.get('mention',''),
        'frequency': int(n.get('frequency:int') or n.get('frequency') or 0),
        'node_type': n.get('node_type:LABEL') or n.get('node_type') or 'ENTITY',
        'sections': [s for s in (n.get('sections','').split('|') if n.get('sections') else []) if s]
    } for n in nodes), batch_size):
        if dry:
            continue
        session.run(cypher, rows=batch)


def load_relationships(session, rels: List[Dict[str, str]], batch_size: int, dry: bool=False):
    cypher = (
        "UNWIND $rows AS row MATCH (s:ENTITY {id: row.source}) MATCH (t:ENTITY {id: row.target}) "
        "MERGE (s)-[r:REL {type: row.type}]->(t) "
        "SET r.method = row.method, r.trigger = row.trigger, r.evidence_span = row.evidence_span, "
        "r.section = row.section_heading, r.sentence_id = row.sentence_id"
    )
    for batch in chunk_iter(({
        'source': r[':START_ID'],
        'target': r[':END_ID'],
        'type': r.get('type:TYPE') or r.get('type') or 'RELATED_TO',
        'method': r.get('method',''),
        'trigger': r.get('trigger') or None,
        'evidence_span': (r.get('evidence_span') or '').replace('\n',' ').strip(),
        'section_heading': r.get('section_heading') or None,
        'sentence_id': int(r['sentence_id:int']) if r.get('sentence_id:int') and r['sentence_id:int'].isdigit() else None
    } for r in rels), batch_size):
        if dry:
            continue
        session.run(cypher, rows=batch)


def ingest(base: Path, pmcid: str, uri: str, user: str, password: str, batch_size: int, purge: bool, dry: bool, min_len: int):
    neo_dir = base / pmcid / 'graph' / 'phase5' / 'neo4j'
    nodes_path = neo_dir / 'nodes.csv'
    rels_path = neo_dir / 'relationships.csv'
    if not nodes_path.exists() or not rels_path.exists():
        raise SystemExit(f"Missing nodes/relationships CSV in {neo_dir}, run phase5_graph first.")
    nodes = read_csv(nodes_path)
    rels = read_csv(rels_path)
    nodes = filter_nodes(nodes, min_len=min_len)
    with open_driver(uri, user, password) as driver:
        with driver.session() as session:
            ensure_indexes(session)
            if purge and not dry:
                purge_db(session)
            load_nodes(session, nodes, batch_size, dry=dry)
            load_relationships(session, rels, batch_size, dry=dry)


def main():  # pragma: no cover
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, help='Base processed directory (e.g. processed_grobid_pdfs)')
    ap.add_argument('--pmcid', required=True, help='PMCID to ingest (folder must exist)')
    ap.add_argument('--uri', default='bolt://localhost:7687')
    ap.add_argument('--user', default='neo4j')
    ap.add_argument('--password', required=True)
    ap.add_argument('--batch-size', type=int, default=1000)
    ap.add_argument('--purge', action='store_true', help='Delete existing graph before ingest')
    ap.add_argument('--dry-run', action='store_true', help='Parse CSVs but do not write to Neo4j')
    ap.add_argument('--min-len', type=int, default=0, help='Filter nodes with mention length < min-len and freq <=1')
    args = ap.parse_args()
    ingest(Path(args.base), args.pmcid, args.uri, args.user, args.password, args.batch_size, args.purge, args.dry_run, args.min_len)


if __name__ == '__main__':  # pragma: no cover
    main()
