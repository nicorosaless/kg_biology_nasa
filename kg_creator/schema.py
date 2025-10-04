from __future__ import annotations
"""Graph schema definition for biological knowledge graph MVP.

Defines 20 node types and 20 relation types with basic metadata.
This is intentionally lightweight; future versions may include
validation logic, ontology fetching, and richer constraints.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional

# -------------------- Node Types --------------------
# Canonical list of 20 node types (upper snake case)
NODE_TYPES: Dict[str, Dict[str, object]] = {
    # Core molecular / genetic
    'GENE_PRODUCT': {
        'description': 'Gene or protein product (merged level).',
        'xrefs_priority': ['HGNC', 'Entrez', 'UniProt'],
        'example': 'TP53'
    },
    'TRANSCRIPT': {
        'description': 'Transcribed RNA variant of a gene.',
        'xrefs_priority': ['EnsemblTranscript', 'RefSeq'],
        'example': 'ENST00000269305'
    },
    'VARIANT': {
        'description': 'Genomic variant or mutation.',
        'xrefs_priority': ['dbSNP', 'ClinVar'],
        'example': 'rs1042522'
    },
    'CHEMICAL': {
        'description': 'Chemical compound or drug.',
        'xrefs_priority': ['ChEBI', 'DrugBank', 'PubChem'],
        'example': 'CHEBI:15377'
    },
    'DISEASE': {
        'description': 'Disease or pathological condition.',
        'xrefs_priority': ['DOID', 'MESH', 'UMLS', 'OMIM'],
        'example': 'DOID:162'
    },
    'PHENOTYPE': {
        'description': 'Phenotypic feature / sign / symptom.',
        'xrefs_priority': ['HPO', 'UMLS'],
        'example': 'HP:0004322'
    },
    'PATHWAY': {
        'description': 'Biological pathway grouping molecular events.',
        'xrefs_priority': ['Reactome', 'KEGG'],
        'example': 'R-HSA-395127'
    },
    'BIOLOGICAL_PROCESS': {
        'description': 'GO Biological Process term.',
        'xrefs_priority': ['GO'],
        'example': 'GO:0006915'
    },
    'MOLECULAR_FUNCTION': {
        'description': 'GO Molecular Function term.',
        'xrefs_priority': ['GO'],
        'example': 'GO:0003700'
    },
    'CELLULAR_COMPONENT': {
        'description': 'GO Cellular Component term.',
        'xrefs_priority': ['GO'],
        'example': 'GO:0005634'
    },
    'CELL_TYPE': {
        'description': 'Specific cell type.',
        'xrefs_priority': ['CL'],
        'example': 'CL:0000236'
    },
    'TISSUE': {
        'description': 'Tissue level anatomical structure.',
        'xrefs_priority': ['UBERON'],
        'example': 'UBERON:0002048'
    },
    'ANATOMICAL_SITE': {
        'description': 'An anatomical location / site (macro).',
        'xrefs_priority': ['UBERON', 'FMA'],
        'example': 'UBERON:0002107'
    },
    'ORGANISM': {
        'description': 'Species / organism.',
        'xrefs_priority': ['NCBITaxon'],
        'example': 'NCBITaxon:9606'
    },
    'PROTEIN_COMPLEX': {
        'description': 'Protein complex (multi-subunit).',
        'xrefs_priority': ['Reactome', 'CORUM'],
        'example': 'CORUM:390'
    },
    'EXPERIMENT': {
        'description': 'Experimental study or assay.',
        'xrefs_priority': ['GEO', 'ArrayExpress'],
        'example': 'GSE00000'
    },
    'EXPERIMENTAL_CONDITION': {
        'description': 'Condition or parameter applied in an experiment (e.g., temperature, timepoint).',
        'xrefs_priority': [],
        'example': '95C_denaturation'
    },
    'REAGENT': {
        'description': 'Laboratory reagent, kit, or consumable used in protocol.',
        'xrefs_priority': [],
        'example': 'TRIzol'
    },
    'SAMPLE': {
        'description': 'Biological sample / specimen.',
        'xrefs_priority': ['BioSample', 'SRA'],
        'example': 'SAMN00000000'
    },
    'PUBLICATION': {
        'description': 'Scientific publication.',
        'xrefs_priority': ['PMID', 'DOI'],
        'example': 'PMID:12345678'
    },
    'CLINICAL_TRIAL': {
        'description': 'Clinical trial record.',
        'xrefs_priority': ['NCT'],
        'example': 'NCT00000000'
    },
    'VARIANT_EFFECT': {
        'description': 'Interpreted functional effect of a variant.',
        'xrefs_priority': [],
        'example': 'loss_of_function'
    }
}

# -------------------- Relation Types --------------------
# 20 relation definitions including domain/range and symmetry
RELATION_TYPES: Dict[str, Dict[str, object]] = {
    'GENE_PRODUCT_ASSOCIATED_WITH_DISEASE': {
        'domain': 'GENE_PRODUCT', 'range': 'DISEASE', 'symmetric': False,
        'description': 'Association between gene product and disease.'
    },
    'GENE_PRODUCT_PARTICIPATES_IN_PROCESS': {
        'domain': 'GENE_PRODUCT', 'range': 'BIOLOGICAL_PROCESS', 'symmetric': False,
        'description': 'Gene product involved in a biological process.'
    },
    'GENE_PRODUCT_LOCATED_IN_CELLULAR_COMPONENT': {
        'domain': 'GENE_PRODUCT', 'range': 'CELLULAR_COMPONENT', 'symmetric': False,
        'description': 'Subcellular localization.'
    },
    'GENE_PRODUCT_HAS_MOLECULAR_FUNCTION': {
        'domain': 'GENE_PRODUCT', 'range': 'MOLECULAR_FUNCTION', 'symmetric': False,
        'description': 'Assigned molecular function.'
    },
    'GENE_PRODUCT_INVOLVED_IN_PATHWAY': {
        'domain': 'GENE_PRODUCT', 'range': 'PATHWAY', 'symmetric': False,
        'description': 'Participation of gene product in pathway.'
    },
    'CHEMICAL_MODULATES_GENE_PRODUCT': {
        'domain': 'CHEMICAL', 'range': 'GENE_PRODUCT', 'symmetric': False,
        'description': 'Chemical modulates (activates/inhibits) gene product.'
    },
    'CHEMICAL_TREATS_DISEASE': {
        'domain': 'CHEMICAL', 'range': 'DISEASE', 'symmetric': False,
        'description': 'Therapeutic or indicated treatment relation.'
    },
    'VARIANT_ASSOCIATED_WITH_DISEASE': {
        'domain': 'VARIANT', 'range': 'DISEASE', 'symmetric': False,
        'description': 'Variant linked to disease risk or phenotype.'
    },
    'VARIANT_ALTERS_GENE_PRODUCT': {
        'domain': 'VARIANT', 'range': 'GENE_PRODUCT', 'symmetric': False,
        'description': 'Variant changes structure/function of gene product.'
    },
    'DISEASE_HAS_PHENOTYPE': {
        'domain': 'DISEASE', 'range': 'PHENOTYPE', 'symmetric': False,
        'description': 'Phenotypic feature observed in disease.'
    },
    'PHENOTYPE_OBSERVED_IN_ORGANISM': {
        'domain': 'PHENOTYPE', 'range': 'ORGANISM', 'symmetric': False,
        'description': 'Phenotype observed in a given organism/species.'
    },
    'GENE_PRODUCT_EXPRESSED_IN_TISSUE': {
        'domain': 'GENE_PRODUCT', 'range': 'TISSUE', 'symmetric': False,
        'description': 'Expression evidence in tissue.'
    },
    'GENE_PRODUCT_EXPRESSED_IN_CELL_TYPE': {
        'domain': 'GENE_PRODUCT', 'range': 'CELL_TYPE', 'symmetric': False,
        'description': 'Expression evidence in cell type.'
    },
    'PROCESS_OCCURS_IN_ANATOMICAL_SITE': {
        'domain': 'BIOLOGICAL_PROCESS', 'range': 'ANATOMICAL_SITE', 'symmetric': False,
        'description': 'Process localized to an anatomical site.'
    },
    'CHEMICAL_PART_OF_PATHWAY': {
        'domain': 'CHEMICAL', 'range': 'PATHWAY', 'symmetric': False,
        'description': 'Chemical participates in pathway context.'
    },
    'PATHWAY_INVOLVES_PROCESS': {
        'domain': 'PATHWAY', 'range': 'BIOLOGICAL_PROCESS', 'symmetric': False,
        'description': 'Pathway includes biological process component.'
    },
    'GENE_PRODUCT_INTERACTS_WITH_GENE_PRODUCT': {
        'domain': 'GENE_PRODUCT', 'range': 'GENE_PRODUCT', 'symmetric': True,
        'description': 'Physical or functional interaction (symmetric).'
    },
    'PUBLICATION_EVIDENCES_ENTITY': {
        'domain': 'PUBLICATION', 'range': '*', 'symmetric': False,
        'description': 'Publication provides evidence about entity.'
    },
    'PUBLICATION_EVIDENCES_RELATION': {
        'domain': 'PUBLICATION', 'range': 'RELATION', 'symmetric': False,
        'description': 'Publication supports a specific relation.'
    },
    'ORGANISM_HAS_TISSUE': {
        'domain': 'ORGANISM', 'range': 'TISSUE', 'symmetric': False,
        'description': 'An organism contains a tissue (anatomical hierarchy).'
    },
    # --- Added for enriched first-wave semantic extraction ---
    'CELL_TYPE_INVOLVED_IN_PROCESS': {
        'domain': 'CELL_TYPE', 'range': 'BIOLOGICAL_PROCESS', 'symmetric': False,
        'description': 'Cell type participates in or is affected by a biological process.'
    },
    'PATHWAY_REGULATES_PROCESS': {
        'domain': 'PATHWAY', 'range': 'BIOLOGICAL_PROCESS', 'symmetric': False,
        'description': 'Pathway modulates or regulates a biological process.'
    },
    'CHEMICAL_AFFECTS_PROCESS': {
        'domain': 'CHEMICAL', 'range': 'BIOLOGICAL_PROCESS', 'symmetric': False,
        'description': 'Chemical perturbs or influences a biological process.'
    },
    'CELL_TYPE_ASSOCIATED_WITH_PHENOTYPE': {
        'domain': 'CELL_TYPE', 'range': 'PHENOTYPE', 'symmetric': False,
        'description': 'Association between a cell type and a phenotypic feature.'
    },
    'ENVIRONMENT_MODULATES_PROCESS': {
        'domain': 'PHENOTYPE', 'range': 'BIOLOGICAL_PROCESS', 'symmetric': False,
        'description': 'Environmental / contextual condition (e.g. microgravity) modulates a process.'
    }
}

# Quick reverse index for validation usage if needed
NODE_TYPE_SET = set(NODE_TYPES.keys())
RELATION_TYPE_SET = set(RELATION_TYPES.keys())

# Mapping from raw NER labels (normalized earlier) or HF-specific labels to schema node types
# Option A choices: BIOLOGICAL_STRUCTURE -> ANATOMICAL_SITE; SIGN_SYMPTOM -> PHENOTYPE;
# DIAGNOSTIC_PROCEDURE & LAB_VALUE -> EXPERIMENT; fallback mappings provided.
LABEL_TO_NODE_TYPE = {
    # Direct biological mappings
    'GENE': 'GENE_PRODUCT', 'GENE_PRODUCT': 'GENE_PRODUCT', 'PROTEIN': 'GENE_PRODUCT',
    'CHEMICAL': 'CHEMICAL', 'DRUG': 'CHEMICAL',
    'DISEASE': 'DISEASE', 'DISORDER': 'DISEASE',
    'PATHWAY': 'PATHWAY', 'PROCESS': 'BIOLOGICAL_PROCESS', 'BIOLOGICAL_PROCESS': 'BIOLOGICAL_PROCESS',
    'MOLECULAR_FUNCTION': 'MOLECULAR_FUNCTION', 'CELLULAR_COMPONENT': 'CELLULAR_COMPONENT',
    'CELL': 'CELL_TYPE', 'CELL_TYPE': 'CELL_TYPE', 'CELL_LINE': 'CELL_TYPE',
    'TISSUE': 'TISSUE', 'ANATOMY': 'ANATOMICAL_SITE', 'ANATOMICAL_SITE': 'ANATOMICAL_SITE',
    'SPECIES': 'ORGANISM', 'ORGANISM': 'ORGANISM',
    'VARIANT': 'VARIANT', 'MUTATION': 'VARIANT',
    'PHENOTYPE': 'PHENOTYPE', 'SIGN_SYMPTOM': 'PHENOTYPE',
    'BIOLOGICAL_STRUCTURE': 'ANATOMICAL_SITE',
    # Procedures / measurements
    'DIAGNOSTIC_PROCEDURE': 'EXPERIMENT', 'LAB_VALUE': 'EXPERIMENT',
    # Descriptions - not mapped (could be ignored or mapped to PHENOTYPE); keep None to skip
    'DETAILED_DESCRIPTION': None,
    # Other HF possible labels fallback
    'COREFERENCE': None
}

__all__ = [
    'NODE_TYPES', 'RELATION_TYPES', 'NODE_TYPE_SET', 'RELATION_TYPE_SET', 'LABEL_TO_NODE_TYPE'
]
