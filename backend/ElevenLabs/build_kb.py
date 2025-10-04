import csv
import json
import os
import re
from typing import List, Dict

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

"""
Build a lightweight knowledge base JSON from a CSV of PMC article links.

Input CSV format:
  Title,Link

For each link, we will try to fetch the HTML page and extract:
- title (fallback to CSV title)
- abstract
- key sections: Results and Conclusions (if present)
- metadata: pmcid, doi (when available)

Output JSONL (one JSON per line) that can be uploaded to an LLM knowledge base
or used to seed an ElevenLabs Agent knowledge base:
  {
    "id": "PMC4136787",
    "url": "https://...",
    "title": "...",
    "abstract": "...",
    "sections": {
      "results": "...",
      "conclusions": "..."
    },
    "metadata": {"pmcid": "PMC...", "doi": "10.xxxx/..."}
  }

Notes:
- Keeps network usage minimal and robust with timeouts.
- Skips entries on repeated failures; writes partials when possible.
- Designed for quick hackathon setup (not exhaustive parsing).
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
}

PMC_RE = re.compile(r"/pmc/articles/(PMC\d+)/")
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def extract_pmcid(url: str) -> str:
    m = PMC_RE.search(url)
    return m.group(1) if m else ""


def fetch_html(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def text_or_none(el) -> str:
    if not el:
        return ""
    return re.sub(r"\s+", " ", el.get_text(" ").strip())


def find_abstract(soup: BeautifulSoup) -> str:
    # Common PMC patterns
    abs_sel = [
        "section[title='Abstract']",
        "div.abstract",
        "section#abstract",
        "div#abstract",
    ]
    for sel in abs_sel:
        el = soup.select_one(sel)
        if el:
            return text_or_none(el)
    # Fallback by heading text
    for h in soup.find_all(["h2", "h3", "h4"]):
        if h.get_text(strip=True).lower().startswith("abstract"):
            # grab following sibling paragraphs
            parts = []
            sib = h.find_next_sibling()
            while sib and sib.name in ("p", "div", "section"):
                parts.append(text_or_none(sib))
                sib = sib.find_next_sibling()
            return " ".join(p for p in parts if p)
    return ""


def find_section_by_heading(soup: BeautifulSoup, startswith: str) -> str:
    needle = startswith.lower()
    for h in soup.find_all(["h2", "h3", "h4"]):
        txt = h.get_text(" ", strip=True).lower()
        if txt.startswith(needle):
            parts = []
            sib = h.find_next_sibling()
            while sib and sib.name in ("p", "div", "section", "ul", "ol", "table"):
                parts.append(text_or_none(sib))
                sib = sib.find_next_sibling()
            return " ".join(p for p in parts if p)
    return ""


def find_doi(soup: BeautifulSoup) -> str:
    # Try meta tags first
    for name in ("citation_doi", "dc.identifier", "doi"):
        m = soup.find("meta", attrs={"name": name})
        if m and m.get("content"):
            return m["content"].strip()
    # Fallback: search text
    m = DOI_RE.search(soup.get_text(" ", strip=True))
    return m.group(0) if m else ""


def build_kb_record(title: str, url: str, soup: BeautifulSoup) -> Dict:
    pmcid = extract_pmcid(url)
    page_title = soup.title.get_text(strip=True) if soup.title else ""

    abstract = find_abstract(soup)
    results = find_section_by_heading(soup, "results")
    conclusions = find_section_by_heading(soup, "conclusion")
    doi = find_doi(soup)

    return {
        "id": pmcid or page_title or title[:80],
        "url": url,
        "title": title or page_title,
        "abstract": abstract,
        "sections": {
            "results": results,
            "conclusions": conclusions,
        },
        "metadata": {
            "pmcid": pmcid,
            "doi": doi,
        },
    }


def create_kb_from_csv(csv_path: str, out_path: str, limit: int | None = None):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(csv_path, newline="", encoding="utf-8") as f, open(out_path, "w", encoding="utf-8") as out:
        reader = csv.DictReader(f)
        rows = list(reader)
        if limit:
            rows = rows[:limit]

        for row in tqdm(rows, desc="Building KB"):
            title = (row.get("Title") or "").strip()
            url = (row.get("Link") or "").strip()
            if not url:
                continue
            soup = fetch_html(url)
            if not soup:
                # write minimal record
                rec = {
                    "id": extract_pmcid(url) or title[:80] or url,
                    "url": url,
                    "title": title,
                    "abstract": "",
                    "sections": {"results": "", "conclusions": ""},
                    "metadata": {"pmcid": extract_pmcid(url), "doi": ""},
                }
                out.write(json.dumps(rec) + "\n")
                continue

            rec = build_kb_record(title, url, soup)
            out.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create a simple KB JSONL from NASA PMC CSV")
    parser.add_argument("--csv", default="ElevenLabs/SB_publication_PMC.csv", help="Path to input CSV")
    parser.add_argument("--out", default="ElevenLabs/kb_publications.jsonl", help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=50, help="Process only first N rows (set 0 for all)")
    args = parser.parse_args()

    lim = None if args.limit == 0 else args.limit
    create_kb_from_csv(args.csv, args.out, limit=lim)
    print(f"KB written to {args.out}")
