from __future__ import annotations
"""Lightweight normalization helpers for entity post-processing.

Functions here are intentionally heuristic and fast; they do not depend on
external ontologies. Future versions can plug in ontology services.
"""
import re
from typing import Optional

GENE_REGEX = re.compile(r'^[A-Z0-9]{2,8}$')

PATHWAY_WHITELIST = {
    'HIPPO', 'PI3K-AKT', 'MAPK', 'NOTCH', 'WNT', 'MTOR', 'RAS-RAF-MEK-ERK'
}

GENE_WHITELIST = {
    'TP53', 'VEGF', 'BAX', 'YAP1', 'RAS', 'ERK', 'NF-ΚB', 'NF-ΚΒ', 'NF-ΚΒ', 'FAK'
}

STOP_TERMS = {
    'enhance','enhances','enhanced','enhancing',
    'increase','increases','increased','increasing',
    'reduce','reduces','reduced','reducing','reduction',
    'decrease','decreases','decreased','decreasing','decreased',
    'normal','balance','survival','review'
}

def is_pathway(token: str) -> bool:
    t = token.upper().replace('–','-')
    return t in PATHWAY_WHITELIST


def is_gene_symbol(token: str) -> bool:
    t = token.upper()
    if t in GENE_WHITELIST:
        return True
    # Accept NF-κB variants
    if t.startswith('NF-'):
        return True
    return bool(GENE_REGEX.match(t))


def should_filter_span(mention: str) -> bool:
    low = mention.lower()
    if low in STOP_TERMS:
        return True
    return False


def canonical_form(mention: str, preserve_case: bool) -> str:
    if preserve_case:
        return mention.upper()
    base = mention.lower()
    # plural to singular (simple heuristics)
    if base.endswith('ies') and len(base) > 4:
        base = base[:-3] + 'y'
    elif base.endswith('s') and not base.endswith('ss') and len(base) > 4:
        base = base[:-1]
    return base


def merge_fragment(a_text: str, b_text: str) -> Optional[str]:
    # Combine pieces like 'costim' + 'ulatory proteins' => 'costimulatory proteins'
    if not b_text:
        return None
    if b_text[0].islower() and len(a_text) <= 10:
        candidate = (a_text + b_text).replace('  ', ' ')
        if len(candidate) <= 40 and any(ch.isalpha() for ch in candidate):
            return candidate
    return None


__all__ = [
    'is_pathway','is_gene_symbol','should_filter_span','canonical_form','merge_fragment',
    'PATHWAY_WHITELIST','GENE_WHITELIST','STOP_TERMS'
]
