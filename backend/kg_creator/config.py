from __future__ import annotations

# Config centralizada para NER / Relaciones
CONFIG = {
    'ner': {
        # Proveedores activados (orden de prioridad). Valores posibles: 'spacy', 'hf'
    'providers': ['hf','spacy'],  # Hybrid: HF first for biomedical specificity, spaCy fallback
        # Modelos spaCy (se usarán si están instalados; NO se aborta si faltan)
        'spacy_models': [
            'en_core_web_sm'  # Para sentence split + NER general (fallback)
            # SciSpaCy opcionales (requieren build nmslib):
            # 'en_ner_bc5cdr_md',
            # 'en_ner_bionlp13cg_md'
        ],
        # Modelo HuggingFace para NER biomédico (token-classification). Se intentará cargar si transformers está disponible.
        'hf_model': 'd4data/biomedical-ner-all',
        'auto_download': True,  # descargar modelos faltantes si es posible
        'min_len': 2,
        'max_len': 80,
        'merge_overlaps': True,
        'filter_types': None,  # usar todos los tipos que reporte el modelo
        'max_sentence_chars': 5000
    },
    'relations': {
        'enable_patterns': True,
        'pattern_verbs': {
            'ACTIVATES': ['activate','stimulate','upregulate','induce'],
            'INHIBITS': ['inhibit','suppress','downregulate','block'],
            'REGULATES': ['regulate','modulate','control','affect'],
            'EXPRESSED_IN': ['express','present','detected'],
            'INTERACTS_WITH': ['interact','bind','associate','complex']
        },
        'min_pattern_conf': 0.8,
        'cooccur_type': 'COOCCURS_SENT',
        'allow_same_type_pairs': False,
        'max_entities_pattern_sentence': 40
    }
}

# === Visualization config (for UI-friendly subgraph exports) ===
VISUALIZATION = {
    # Maximum nodes to expose in lightweight UI graph (focus subgraph)
    'max_nodes': 120,
    # Hard cut after sorting by (degree desc, frequency desc)
    'max_nodes_strict': 80,
    # Minimum frequency (occurrences / sentence mentions) to keep in focus
    'min_frequency': 1,
    # Optional whitelist node types to prioritize (others may be downsampled)
    'priority_types': ['GENE_PRODUCT','PATHWAY','DISEASE','PHENOTYPE'],
    # Relative node size range (will be scaled later)
    'node_size': {'min': 4, 'max': 28},
    # Color palette per node_type (fallback -> gray)
    'colors': {
        'GENE_PRODUCT': '#1f77b4',
        'PATHWAY': '#ff7f0e',
        'DISEASE': '#d62728',
        'PHENOTYPE': '#9467bd',
        'CHEMICAL': '#17becf',
        'CELL_TYPE': '#2ca02c',
        'SPECIES': '#8c564b',
        'PROCESS': '#e377c2',
        'VARIANT': '#7f7f7f',
        'PUBLICATION': '#bcbd22',
        'REAGENT': '#8dd3c7',
        'EXPERIMENTAL_CONDITION': '#fb8072'
    },
    # Layout algorithm: 'radial' | 'circular' | 'random'
    'layout': 'radial'
}

# === Section Subgraph (per-section mini-graphs) ===
SECTION_SUBGRAPH = {
    'enabled': True,
    # Maximum nodes per section subgraph (after filtering/prioritizing)
    'max_nodes': 40,
    # Node ranking strategy: 'degree_frequency' or 'frequency'
    'ranking': 'degree_frequency',
    # Minimum frequency to include; 1 keeps everything
    'min_frequency': 1,
    # Include cross-section edges? (edges whose source/target sections differ)
    'include_cross_section_edges': False,
    # Normalize section heading slugs to filesystem-safe names
    'slug_max_len': 40
}

# === Atajos / constantes derivadas para evitar acceder al dict en cada módulo ===
SPACY_MODELS = CONFIG['ner']['spacy_models']
NER_PROVIDERS = CONFIG['ner']['providers']
HF_MODEL = CONFIG['ner']['hf_model']

# Expandir verbos -> tipo de relación (lemma -> REL_TYPE)
RELATION_VERBS = {
    lemma: rel_type
    for rel_type, verbs in CONFIG['relations']['pattern_verbs'].items()
    for lemma in verbs
}

MAX_ENTITIES_VERB_PATTERN_SENT = CONFIG['relations']['max_entities_pattern_sentence']

# Normalización de etiquetas heterogéneas a un set canónico
ENTITY_LABEL_MAPPING = {
    # Genes / Proteínas
    'GENE': 'GENE', 'GENE_OR_GENE_PRODUCT': 'GENE', 'GENE_OR_PROTEIN': 'GENE', 'PROTEIN': 'GENE',
    'PROTEIN_FAMILY': 'GENE', 'DNA': 'GENE', 'RNA': 'GENE',
    # Químicos / Drogas
    'CHEMICAL': 'CHEMICAL', 'CHEM': 'CHEMICAL', 'DRUG': 'CHEMICAL', 'CHEBI': 'CHEMICAL',
    # Enfermedades / Fenotipos
    'DISEASE': 'DISEASE', 'DISEASE_OR_SYNDROME': 'DISEASE', 'PATHOLOGY': 'DISEASE', 'PHENOTYPE': 'PHENOTYPE',
    # Células / Tejidos / Anatomía
    'CELL': 'CELL', 'CELL_TYPE': 'CELL', 'CELL_LINE': 'CELL_LINE', 'TISSUE': 'TISSUE',
    'ANATOMICAL_SYSTEM': 'ANATOMY', 'BODY_PART': 'ANATOMY', 'ORGAN': 'ANATOMY', 'ORGANISM_SUBSTANCE': 'ANATOMY',
    # Organismos / Especies
    'SPECIES': 'SPECIES', 'ORGANISM': 'SPECIES', 'BACTERIUM': 'SPECIES', 'VIRUS': 'SPECIES',
    # Procesos biológicos
    'PROCESS': 'PROCESS', 'BIOLOGICAL_PROCESS': 'PROCESS', 'PATHWAY': 'PATHWAY',
    # Otros comunes
    'MUTATION': 'VARIANT', 'VARIANT': 'VARIANT'
}

__all__ = [
    'CONFIG', 'SPACY_MODELS', 'NER_PROVIDERS', 'HF_MODEL', 'RELATION_VERBS',
    'MAX_ENTITIES_VERB_PATTERN_SENT', 'ENTITY_LABEL_MAPPING', 'VISUALIZATION', 'SECTION_SUBGRAPH'
]

# Connectivity enforcement (used in phase5)
FORCE_PUBLICATION_CONNECTIVITY = True  # if True, will connect all nodes to publication when multiple components remain

# When True, phase5 will only persist the graph artifacts required by the UI:
# - graph_core.json
# - section_overview.json
# - section_*.json (per-section subgraphs)
# It will SKIP: graph.json (full), stats.json (stats already embedded in core), graph_vis.json, neo4j CSV exports.
# Set to False to keep all diagnostic / integration exports.
PHASE5_MINIMAL_OUTPUT = True
