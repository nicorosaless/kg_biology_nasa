"""Directly ingest the generated graph into a running Neo4j instance using the Bolt driver.

Reads credentials from environment variables (loaded via python-dotenv if present):
  NEO4J_URI (default bolt://localhost:7687)
  NEO4J_USER (default neo4j)
  NEO4J_PASSWORD (required if auth enabled)

Usage:
  python -m kg_creator.ingest_neo4j --graph graph.json

Prerequisites:
  pip install neo4j python-dotenv
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path

try:
    from neo4j import GraphDatabase
except ImportError:  # pragma: no cover
    GraphDatabase = None  # type: ignore

try:
    from dotenv import load_dotenv  # type: ignore
except ImportError:  # pragma: no cover
    def load_dotenv():
        return False


def get_driver():
    load_dotenv()
    uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
    user = os.getenv('NEO4J_USER', 'neo4j')
    pwd = os.getenv('NEO4J_PASSWORD')
    if GraphDatabase is None:
        raise SystemExit("neo4j driver not installed. Run: pip install neo4j python-dotenv")
    if not pwd:
        raise SystemExit("NEO4J_PASSWORD not set in environment or .env file")
    return GraphDatabase.driver(uri, auth=(user, pwd))


CREATE_ENTITIES = """
UNWIND $rows AS row
MERGE (e:Entity {id: row.id})
SET e.type = row.type, e.name = row.name, e.source = row.source
"""

CREATE_RELATIONS = """
UNWIND $rows AS row
MATCH (s:Entity {id: row.source})
MATCH (t:Entity {id: row.target})
MERGE (s)-[r:RELATION {type: row.type}]->(t)
SET r.evidence = row.evidence
"""


def chunk(iterable, size=500):
    buf = []
    for item in iterable:
        buf.append(item)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def ingest(graph_path: Path, batch_size: int = 500, wipe: bool = False):
    data = json.loads(graph_path.read_text(encoding='utf-8'))
    driver = get_driver()
    with driver.session() as session:
        if wipe:
            print("[INFO] Wiping existing nodes and relationships ...")
            session.run("MATCH ()-[r]-() DELETE r")
            session.run("MATCH (n) DELETE n")
        for batch in chunk(data['entities'], batch_size):
            session.run(CREATE_ENTITIES, rows=batch)
        for batch in chunk(data['relations'], batch_size):
            session.run(CREATE_RELATIONS, rows=batch)
    driver.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--graph', type=Path, default=Path('graph.json'))
    p.add_argument('--batch-size', type=int, default=500)
    p.add_argument('--wipe', action='store_true', help='Limpiar completamente la base antes de ingestar')
    args = p.parse_args()
    ingest(args.graph, args.batch_size, args.wipe)
    print(f"Ingested graph from {args.graph} (wipe={args.wipe})")


if __name__ == '__main__':
    main()
