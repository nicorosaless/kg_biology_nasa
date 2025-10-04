import json
import os
from pathlib import Path
from typing import Dict

"""
Export KB JSONL records into simple Markdown files, one per document.
Each file contains: Title, URL, DOI, Abstract, Results, Conclusions.

Usage:
  python ElevenLabs/export_kb_text.py --in ElevenLabs/kb_publications.jsonl --out ElevenLabs/kb_text
"""


def record_to_markdown(rec: Dict) -> str:
    title = rec.get("title", "Untitled")
    url = rec.get("url", "")
    meta = rec.get("metadata", {}) or {}
    doi = meta.get("doi", "")
    pmcid = meta.get("pmcid", "")
    abstract = (rec.get("abstract") or "").strip()
    sections = rec.get("sections", {}) or {}
    results = (sections.get("results") or "").strip()
    conclusions = (sections.get("conclusions") or "").strip()

    lines = [
        f"# {title}",
        "",
        f"- URL: {url}" if url else "",
        f"- DOI: {doi}" if doi else "",
        f"- PMCID: {pmcid}" if pmcid else "",
        "",
        "## Abstract",
        abstract or "(no abstract)",
        "",
        "## Results",
        results or "(no results)",
        "",
        "## Conclusions",
        conclusions or "(no conclusions)",
        "",
    ]
    return "\n".join([l for l in lines if l is not None])


def export_jsonl_to_md(jsonl_path: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    count = 0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            pmcid = (rec.get("metadata", {}) or {}).get("pmcid")
            base = pmcid or rec.get("id") or f"doc_{count+1}"
            safe = "".join(c for c in base if c.isalnum() or c in ("-", "_"))
            filepath = Path(out_dir) / f"{safe}.md"
            with open(filepath, "w", encoding="utf-8") as out:
                out.write(record_to_markdown(rec))
            count += 1
    return count


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export KB JSONL to per-record Markdown files")
    parser.add_argument("--in", dest="inp", default="ElevenLabs/kb_publications.jsonl", help="Input JSONL path")
    parser.add_argument("--out", dest="out", default="ElevenLabs/kb_text", help="Output directory")
    args = parser.parse_args()

    n = export_jsonl_to_md(args.inp, args.out)
    print(f"Exported {n} markdown files to {args.out}")
