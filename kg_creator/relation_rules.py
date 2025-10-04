from __future__ import annotations
"""Centralized relation rule definitions (co-occurrence + verbs)."""
from typing import Dict, Tuple, Set

# Co-occurrence mapping (domain_type, range_type) -> relation type
COOC_RULES: Dict[Tuple[str,str], str] = {
    ('GENE_PRODUCT','DISEASE'): 'GENE_PRODUCT_ASSOCIATED_WITH_DISEASE',
    ('VARIANT','DISEASE'): 'VARIANT_ASSOCIATED_WITH_DISEASE',
    ('CHEMICAL','GENE_PRODUCT'): 'CHEMICAL_MODULATES_GENE_PRODUCT',
    ('GENE_PRODUCT','PATHWAY'): 'GENE_PRODUCT_INVOLVED_IN_PATHWAY',
    ('GENE_PRODUCT','BIOLOGICAL_PROCESS'): 'GENE_PRODUCT_PARTICIPATES_IN_PROCESS',
    ('GENE_PRODUCT','CELLULAR_COMPONENT'): 'GENE_PRODUCT_LOCATED_IN_CELLULAR_COMPONENT',
    ('GENE_PRODUCT','MOLECULAR_FUNCTION'): 'GENE_PRODUCT_HAS_MOLECULAR_FUNCTION',
    ('GENE_PRODUCT','TISSUE'): 'GENE_PRODUCT_EXPRESSED_IN_TISSUE',
    ('GENE_PRODUCT','CELL_TYPE'): 'GENE_PRODUCT_EXPRESSED_IN_CELL_TYPE',
    ('DISEASE','PHENOTYPE'): 'DISEASE_HAS_PHENOTYPE',
    ('BIOLOGICAL_PROCESS','ANATOMICAL_SITE'): 'PROCESS_OCCURS_IN_ANATOMICAL_SITE',
    ('CHEMICAL','PATHWAY'): 'CHEMICAL_PART_OF_PATHWAY',
    ('PATHWAY','BIOLOGICAL_PROCESS'): 'PATHWAY_INVOLVES_PROCESS',
    # Added enriched first wave
    ('CELL_TYPE','BIOLOGICAL_PROCESS'): 'CELL_TYPE_INVOLVED_IN_PROCESS',
    ('PATHWAY','BIOLOGICAL_PROCESS'): 'PATHWAY_REGULATES_PROCESS',
    ('CHEMICAL','BIOLOGICAL_PROCESS'): 'CHEMICAL_AFFECTS_PROCESS',
    ('CELL_TYPE','PHENOTYPE'): 'CELL_TYPE_ASSOCIATED_WITH_PHENOTYPE',
}

SYMMETRIC_TYPES: Set[str] = {'GENE_PRODUCT_INTERACTS_WITH_GENE_PRODUCT'}

# Verb lemma -> semantic family
VERB_FAMILIES = {
    'activate':'MODULATE','activates':'MODULATE','promote':'MODULATE','promotes':'MODULATE',
    'enhance':'MODULATE','enhances':'MODULATE','induce':'MODULATE','induces':'MODULATE',
    'inhibit':'MODULATE','inhibits':'MODULATE','suppress':'MODULATE','suppresses':'MODULATE',
    'disrupt':'MODULATE','disrupts':'MODULATE','modulate':'MODULATE','modulates':'MODULATE',
    'reduce':'MODULATE','reduces':'MODULATE'
}

def map_verb_relation(src_type: str, tgt_type: str, verb_family: str) -> str | None:
    if verb_family != 'MODULATE':
        return None
    # Source categories that tend to modulate processes/phenotypes
    if src_type == 'CHEMICAL' and tgt_type == 'GENE_PRODUCT':
        return 'CHEMICAL_MODULATES_GENE_PRODUCT'
    if src_type == 'PATHWAY' and tgt_type == 'BIOLOGICAL_PROCESS':
        return 'PATHWAY_REGULATES_PROCESS'
    if src_type == 'CHEMICAL' and tgt_type == 'BIOLOGICAL_PROCESS':
        return 'CHEMICAL_AFFECTS_PROCESS'
    if src_type == 'CELL_TYPE' and tgt_type == 'BIOLOGICAL_PROCESS':
        return 'CELL_TYPE_INVOLVED_IN_PROCESS'
    if src_type == 'CELL_TYPE' and tgt_type == 'PHENOTYPE':
        return 'CELL_TYPE_ASSOCIATED_WITH_PHENOTYPE'
    return None

__all__ = ['COOC_RULES','SYMMETRIC_TYPES','VERB_FAMILIES','map_verb_relation']
