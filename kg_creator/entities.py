"""Simple heuristic entity extraction.

Goal: Provide a lightweight, easily replaceable layer before plugging in a more
sophisticated NER / ontology matcher / LLM.

Entity Types (initial):
- CHEMICAL: naive detection of common chemical suffixes / elements
- ORGANISM: detect Latin binomials (Genus species pattern)
- SECTION_CONCEPT: key domain terms from section text

These are placeholders; upgrade logic as needed.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Iterable, Tuple, Dict, Set

BINOMIAL_RE = re.compile(r"\b([A-Z][a-z]+\s+[a-z]{3,})\b")
CHEMICAL_RE = re.compile(r"\b([A-Z][a-z]?[a-z]?\d{0,2}|[A-Z]{2,})\b")  # crude token filter
KEY_TERMS = [
    'gene', 'genome', 'protein', 'enzyme', 'mutation', 'pathway', 'biosynthesis',
    'metabolism', 'signaling', 'expression', 'transcription', 'regulation'
]
KEY_TERMS_RE = re.compile(r"|".join(re.escape(t) for t in KEY_TERMS), re.IGNORECASE)

STOPLIKE = {"The", "This", "That", "With", "From", "Using"}

@dataclass
class Entity:
    id: str
    type: str
    name: str
    source: str  # e.g., path or document id

@dataclass
class Relation:
    id: str
    type: str
    source: str
    target: str
    evidence: str

class EntityAccumulator:
    def __init__(self):
        self.entities: Dict[Tuple[str, str], Entity] = {}
        self.relations: Dict[Tuple[str, str, str], Relation] = {}
        self._entity_index = 0
        self._relation_index = 0

    def _next_entity_id(self) -> str:
        self._entity_index += 1
        return f"E{self._entity_index}"

    def _next_relation_id(self) -> str:
        self._relation_index += 1
        return f"R{self._relation_index}"

    def add_entity(self, type_: str, name: str, source: str) -> Entity:
        key = (type_, name)
        if key in self.entities:
            return self.entities[key]
        ent = Entity(id=self._next_entity_id(), type=type_, name=name, source=source)
        self.entities[key] = ent
        return ent

    def add_relation(self, type_: str, source: Entity, target: Entity, evidence: str) -> Relation:
        key = (type_, source.id, target.id)
        if key in self.relations:
            return self.relations[key]
        rel = Relation(id=self._next_relation_id(), type=type_, source=source.id, target=target.id, evidence=evidence)
        self.relations[key] = rel
        return rel

    def as_dict(self):
        return {
            'entities': [e.__dict__ for e in self.entities.values()],
            'relations': [r.__dict__ for r in self.relations.values()],
        }


def extract_entities(text: str, doc_id: str, acc: EntityAccumulator) -> None:
    # Binomials (organisms)
    for match in BINOMIAL_RE.finditer(text):
        cand = match.group(1).strip()
        first = cand.split()[0]
        if first in STOPLIKE:
            continue
        acc.add_entity('ORGANISM', cand, doc_id)

    # Key domain terms
    for match in KEY_TERMS_RE.finditer(text):
        term = match.group(0).lower()
        acc.add_entity('SECTION_CONCEPT', term, doc_id)

    # Very crude chemical-like tokens (uppercase short tokens) - placeholder
    for tok in set(re.findall(r"\b[A-Z]{2,}\b", text)):
        if len(tok) <= 5 and tok not in {'AND', 'THE', 'WITH'}:
            acc.add_entity('CHEMICAL', tok, doc_id)

__all__ = ['Entity', 'Relation', 'EntityAccumulator', 'extract_entities']
