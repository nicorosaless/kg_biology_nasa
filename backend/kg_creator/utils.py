from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

GRAPH_SUBDIR = "graph"
# Primary (new) naming: <paper_id>.content.json inside paper root or summary_and_content/
NEW_CONTENT_NAME = "{pmcid}.content.json"
# Legacy suffix still supported for backward compatibility
LEGACY_CONTENT_SUFFIX = ".grobid.content.json"

PHASE_DIRS = {
    1: 'phase1',
    2: 'phase2',
    3: 'phase3',
    4: 'phase4',
    5: 'phase5'
}


def get_paper_dir(base_dir: Path, pmcid: str) -> Path:
    return base_dir / pmcid


def get_graph_root(base_dir: Path, pmcid: str, create: bool = True) -> Path:
    root = get_paper_dir(base_dir, pmcid) / GRAPH_SUBDIR
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def get_phase_dir(base_dir: Path, pmcid: str, phase: int, create: bool = True) -> Path:
    root = get_graph_root(base_dir, pmcid, create)
    pdir = root / PHASE_DIRS[phase]
    if create:
        pdir.mkdir(parents=True, exist_ok=True)
    return pdir


def load_content_json(base_dir: Path, pmcid: str) -> Dict[str, Any]:
    """Carga el JSON de contenido del paper.

    Orden de búsqueda:
      1. processed_grobid_pdfs/<pmcid>/summary_and_content/<pmcid>.content.json
      2. processed_grobid_pdfs/<pmcid>/<pmcid>.content.json
      3. processed_grobid_pdfs/<pmcid>/<pmcid>.grobid.content.json (legacy)
    """
    paper_dir = get_paper_dir(base_dir, pmcid)
    candidates = [
        paper_dir / 'summary_and_content' / NEW_CONTENT_NAME.format(pmcid=pmcid),
        paper_dir / NEW_CONTENT_NAME.format(pmcid=pmcid),
        paper_dir / f"{pmcid}{LEGACY_CONTENT_SUFFIX}"
    ]
    for c in candidates:
        if c.exists():
            return json.loads(c.read_text(encoding='utf-8'))
    raise FileNotFoundError("Missing content file (checked: " + ", ".join(str(c) for c in candidates) + ")")


def save_json(obj: Any, path: Path):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def save_jsonl(rows: Iterable[Dict[str, Any]], path: Path):
    with path.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

__all__ = [
    'get_paper_dir','get_graph_root','get_phase_dir','load_content_json','save_json','save_jsonl','read_jsonl','GRAPH_SUBDIR','PHASE_DIRS','NEW_CONTENT_NAME','LEGACY_CONTENT_SUFFIX'
]
