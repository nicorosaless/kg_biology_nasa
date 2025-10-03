"""Convenience CLI to build the graph then export to Neo4j CSVs.

Example:
python -m kg_creator.run_kg --input processed_grobid_pdfs --graph-out graph.json --neo4j-out neo4j_export
"""
from __future__ import annotations
import argparse
from pathlib import Path
from .build_graph import build_graph, save_graph
from .neo4j_export import export_neo4j


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, default=Path('processed_grobid_pdfs'))
    p.add_argument('--graph-out', type=Path, default=Path('graph.json'))
    p.add_argument('--neo4j-out', type=Path, default=Path('neo4j_export'))
    args = p.parse_args()

    graph = build_graph(args.input)
    save_graph(graph, args.graph_out)
    export_neo4j(graph, args.neo4j_out)
    print(f"Graph JSON: {args.graph_out}\nNeo4j export dir: {args.neo4j_out}")

if __name__ == '__main__':
    main()
