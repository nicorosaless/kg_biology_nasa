#!/usr/bin/env python3
"""
Update kb_publications.txt by:
  a) Removing the 'url' field from each JSONL record
  b) Adding the cluster information for each paper from csvGraph.json

Cluster info added:
  - clusterId (e.g., 'C106')
  - clusterLabel (e.g., 'Macrocluster: Neuroscience & Behavior')

Usage:
  python backend/VoiceAgent/update_kb_publications.py \
    --kb-file backend/VoiceAgent/kb_publications.txt \
    --graph-file frontend/public/data/csvGraph.json \
    [--dry-run]

By default, performs an in-place, atomic update of the kb file and writes a .bak backup.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
from typing import Dict, Tuple


def load_clusters(graph_path: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load mapping dictionaries from csvGraph.json.

    Returns:
      paper_to_cluster_id: maps paperId (e.g., 'PMC4136787') -> clusterId (e.g., 'C106')
      cluster_id_to_label: maps clusterId -> clusterLabel (human-readable name)
    """
    with open(graph_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    paper_to_cluster_id: Dict[str, str] = {}
    for p in data.get("papers", []):
        pid = p.get("id")
        cid = p.get("clusterId")
        if isinstance(pid, str) and isinstance(cid, str):
            paper_to_cluster_id[pid] = cid

    cluster_id_to_label: Dict[str, str] = {}
    for c in data.get("clusters", []):
        cid = c.get("id")
        label = c.get("label")
        if isinstance(cid, str) and isinstance(label, str):
            cluster_id_to_label[cid] = label

    return paper_to_cluster_id, cluster_id_to_label


def process_kb_line(line: str, paper_to_cluster_id: Dict[str, str], cluster_id_to_label: Dict[str, str]) -> str:
    """Transform a single JSONL line: remove 'url', add clusterId/clusterLabel if available.

    Returns the updated JSON object encoded on a single line (with newline).
    Lines that are empty/whitespace are returned as-is.
    """
    if not line.strip():
        return line

    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        # Preserve original line if it can't be decoded, but flag on stderr
        sys.stderr.write("[warn] Skipping non-JSON line (preserved as-is)\n")
        return line

    # Remove URL field if present
    if isinstance(obj, dict) and "url" in obj:
        obj.pop("url", None)

    # Identify paper id
    pid = None
    if isinstance(obj, dict):
        pid = obj.get("id") or obj.get("metadata", {}).get("pmcid")

    # Attach cluster info if available
    if isinstance(pid, str):
        cid = paper_to_cluster_id.get(pid)
        if cid:
            obj["clusterId"] = cid
            label = cluster_id_to_label.get(cid)
            if label:
                obj["clusterLabel"] = label

    return json.dumps(obj, ensure_ascii=False) + "\n"


def update_kb_file(kb_path: str, graph_path: str, dry_run: bool = False) -> None:
    paper_to_cluster_id, cluster_id_to_label = load_clusters(graph_path)

    # Prepare paths for atomic write
    kb_dir = os.path.dirname(os.path.abspath(kb_path))
    tmp_path = os.path.join(kb_dir, os.path.basename(kb_path) + ".tmp")
    bak_path = os.path.join(kb_dir, os.path.basename(kb_path) + ".bak")

    # Stream process lines
    with open(kb_path, "r", encoding="utf-8") as infile:
        if dry_run:
            # Print first few transformed lines to stdout for preview
            preview_count = 0
            for line in infile:
                sys.stdout.write(process_kb_line(line, paper_to_cluster_id, cluster_id_to_label))
                preview_count += 1
                if preview_count >= 5:
                    break
            return

        with open(tmp_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                outfile.write(process_kb_line(line, paper_to_cluster_id, cluster_id_to_label))

    # Backup original and replace atomically
    shutil.copy2(kb_path, bak_path)
    os.replace(tmp_path, kb_path)

    # Basic success message
    sys.stderr.write(f"[info] Updated '{kb_path}'. Backup saved at '{bak_path}'.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove URL and add cluster info to kb_publications JSONL")
    parser.add_argument("--kb-file", default="backend/VoiceAgent/kb_publications.txt", help="Path to kb_publications JSONL file")
    parser.add_argument("--graph-file", default="frontend/public/data/csvGraph.json", help="Path to csvGraph.json")
    parser.add_argument("--dry-run", action="store_true", help="Print a preview of transformed lines instead of updating the file")
    args = parser.parse_args()

    update_kb_file(args.kb_file, args.graph_file, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
