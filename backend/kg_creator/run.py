from __future__ import annotations
from pathlib import Path
import argparse

from . import phase1_parse, phase2_sentences, phase3_entities, phase4_relations, phase5_graph

PHASE_FUNCS = [
    phase1_parse.run,
    phase2_sentences.run,
    phase3_entities.run,
    phase4_relations.run,
    phase5_graph.run
]


def run_phases(base_dir: Path, pmcid: str, phases: list[int]):
    stats = {}
    for p in phases:
        func = PHASE_FUNCS[p-1]
        res = func(base_dir, pmcid)
        stats[f'phase{p}'] = res
    return stats


def parse_phase_selector(sel: str) -> list[int]:
    if sel == 'all':
        return [1,2,3,4,5]
    out = []
    for part in sel.split(','):
        part = part.strip()
        if not part:
            continue
        num = int(part)
        if num < 1 or num > 5:
            raise ValueError('Phase numbers must be between 1 and 5')
        out.append(num)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True, help='Directorio base que contiene las carpetas de cada PMCID')
    ap.add_argument('--pmcid', required=True, help='Identificador PMCID (carpeta con json de grobid)')
    ap.add_argument('--phases', default='all', help='Lista de fases, ej: 1,2,3 o "all"')
    args = ap.parse_args()
    phases = parse_phase_selector(args.phases)
    stats = run_phases(Path(args.base), args.pmcid, phases)
    for k,v in stats.items():
        print(k, v)

if __name__ == '__main__':
    main()
