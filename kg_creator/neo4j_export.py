"""Export graph structures to Neo4j-friendly CSV plus Cypher loader.

Creates three files given a graph dict from build_graph:
- nodes.csv (id:ID,type,name,source)
- relations.csv (:START_ID,:END_ID,type,evidence)
- load.cypher (Cypher script to load the CSVs)
"""
from __future__ import annotations
from pathlib import Path
import csv
from typing import Dict, Any

NODE_HEADERS = ['id:ID', 'type', 'name', 'source']
REL_HEADERS = [':START_ID', ':END_ID', 'type', 'evidence']


def export_neo4j(graph: Dict[str, Any], out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes_p = out_dir / 'nodes.csv'
    rels_p = out_dir / 'relations.csv'
    with nodes_p.open('w', newline='', encoding='utf-8') as nf:
        w = csv.writer(nf)
        w.writerow(NODE_HEADERS)
        for n in graph['entities']:
            w.writerow([n['id'], n['type'], n['name'], n['source']])
    with rels_p.open('w', newline='', encoding='utf-8') as rf:
        w = csv.writer(rf)
        w.writerow(REL_HEADERS)
        for r in graph['relations']:
            w.writerow([r['source'], r['target'], r['type'], r['evidence']])
    (out_dir / 'load.cypher').write_text("""
USING PERIODIC COMMIT 500
LOAD CSV WITH HEADERS FROM 'file:///nodes.csv' AS row
MERGE (n:Entity {id: row.id})
SET n.type = row.type, n.name = row.name, n.source = row.source;

USING PERIODIC COMMIT 500
LOAD CSV WITH HEADERS FROM 'file:///relations.csv' AS row
MATCH (s:Entity {id: row.`:START_ID`})
MATCH (t:Entity {id: row.`:END_ID`})
MERGE (s)-[r:RELATION {type: row.type}]->(t)
SET r.evidence = row.evidence;
""".strip(), encoding='utf-8')

__all__ = ['export_neo4j']
