from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json
import math
import hashlib
import warnings
import importlib
import importlib.util

from .utils import get_phase_dir, save_jsonl
from . import config
from . import schema
from . import normalization as norm

# =============================================================
#   PHASE 3 (Refactor): Model-only NER (no heuristics)
#   Providers (ordered by priority) defined in config.NER_PROVIDERS
#   Current implemented providers: 'spacy', 'hf' (HuggingFace token classification)
# =============================================================

PROVIDERS = config.NER_PROVIDERS
SPACY_MODELS = config.SPACY_MODELS
HF_MODEL_NAME = config.HF_MODEL
LABEL_MAP = config.ENTITY_LABEL_MAPPING

AUTO_DOWNLOAD = config.CONFIG['ner']['auto_download']
MERGE_OVERLAPS = config.CONFIG['ner']['merge_overlaps']
FILTER_TYPES = config.CONFIG['ner']['filter_types']  # None -> keep all
MIN_LEN = config.CONFIG['ner']['min_len']
MAX_LEN = config.CONFIG['ner']['max_len']

# caches
_spacy_models: Dict[str, Any] = {}
_hf_pipeline = None
_hf_cache_dir: Optional[Path] = None

# Simple blacklist of generic proper nouns / section words / sources producing noise
BLACKLIST = {
    'EARTH','PUBMED','INTRODUCTION','ABSTRACT','RESULT','RESULTS','DISCUSSION','CONCLUSION','CONCLUSIONS',
    'FIGURE','TABLE','HTTPS','HTTP','NASA','ELSEVIER','SPRINGER','WILEY'
}

# Words that if the entire mention equals them => filter unless typed as gene by override
LOWER_BLACKLIST = {w.lower() for w in BLACKLIST}

# Suppress specific transformers warnings (FutureWarning + accelerator note)
warnings.filterwarnings(
    'ignore',
    message=r'`clean_up_tokenization_spaces` was not set',
    category=FutureWarning
)

# We'll silence generic UserWarnings from transformers that match accelerator line
warnings.filterwarnings(
    'ignore',
    message=r'.*accelerator e.g. GPU is available.*',
    category=UserWarning
)

def _ensure_spacy_model(name: str):
    if name in _spacy_models:
        return _spacy_models[name]
    spec = importlib.util.find_spec('spacy')
    if spec is None:
        return None
    import spacy  # type: ignore
    try:
        nlp = spacy.load(name)
    except OSError:
        if not AUTO_DOWNLOAD:
            return None
        try:
            from spacy.cli import download  # type: ignore
            download(name)
            nlp = spacy.load(name)
        except Exception:
            return None
    _spacy_models[name] = nlp
    return nlp


def _ensure_hf_pipeline():
    global _hf_pipeline
    if _hf_pipeline is not None:
        return _hf_pipeline
    if 'hf' not in PROVIDERS:
        return None
    if importlib.util.find_spec('transformers') is None:
        return None
    try:
        from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline  # type: ignore
        tok = AutoTokenizer.from_pretrained(HF_MODEL_NAME)
        model = AutoModelForTokenClassification.from_pretrained(HF_MODEL_NAME)
        _hf_pipeline = pipeline('token-classification', model=model, tokenizer=tok, aggregation_strategy='simple')
        return _hf_pipeline
    except Exception:
        _hf_pipeline = None
        return None


def _hf_cache_path(text: str) -> Optional[Path]:
    """Return cache file path for a given text if caching enabled."""
    global _hf_cache_dir
    if _hf_cache_dir is None:
        base = Path('.hf_cache_entities')
        base.mkdir(exist_ok=True)
        _hf_cache_dir = base
    h = hashlib.md5(text.encode('utf-8')).hexdigest()
    return _hf_cache_dir / f'{h}.json'


def load_sentences(base_dir: Path, pmcid: str) -> List[Dict[str, Any]]:
    phase2 = get_phase_dir(base_dir, pmcid, 2)
    path = phase2 / 'sentences.jsonl'
    if not path.exists():
        raise FileNotFoundError('Run phase2 before phase3 (missing sentences.jsonl)')
    sents: List[Dict[str, Any]] = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            sents.append(json.loads(line))
    return sents


# ------------------ Extraction per provider ------------------

def _spacy_entities(text: str) -> List[Tuple[int,int,str,str,str]]:
    spans = []
    for model_name in SPACY_MODELS:
        nlp = _ensure_spacy_model(model_name)
        if not nlp:
            continue
        doc = nlp(text)
        for ent in doc.ents:
            label_raw = ent.label_.upper()
            label_norm = LABEL_MAP.get(label_raw, label_raw)
            if FILTER_TYPES and label_norm not in FILTER_TYPES:
                continue
            mention = ent.text.strip()
            if len(mention) < MIN_LEN or len(mention) > MAX_LEN:
                continue
            spans.append((ent.start_char, ent.end_char, label_norm, mention, f'spacy:{model_name}'))
    return spans


NOISY_MIN_LEN = 3
WHITELIST_SHORT = {"ATP", "DNA", "RNA", "TP53", "EGFR"}
VOWELS = set("aeiouAEIOU")

def _is_noisy(token: str) -> bool:
    if token in WHITELIST_SHORT:
        return False
    if len(token) < NOISY_MIN_LEN:
        return True
    if not any(c in VOWELS for c in token):  # no vowel => likely code fragment
        return True
    return False

# --- Domain-specific heuristics enrichment ---
HOUSEKEEPING_GENES = {"GAPDH","ACTB","HPRT1","GUSB","B2M","RPL13A"}
REAGENTS = {"TRIZOL","RNEASY","QIAGEN","NANODROP","RNASE","DNASE","ETHANOL","ETOH"}
TEMPERATURE_PATTERN = r"(?i)^\d{1,3}(?:°?C|uC)$"  # 95uC, 60uC, 42°C, 4uC
NUMBER_WORDS = {"one","two","three","four","five","six","seven","eight","nine","ten"}

def classify_special_token(mention: str) -> tuple[bool, str | None, str | None]:
    """Return (should_filter, node_type_override, role) for a mention.
    - should_filter True => drop entirely.
    - node_type_override: new node_type (e.g., EXPERIMENTAL_CONDITION, REAGENT)
    - role: semantic role tag (e.g., HOUSEKEEPING_GENE)
    """
    import re
    if not mention:
        return True, None, None
    m = mention.strip()
    upper = m.upper()
    lower = m.lower()
    # Temperature condition
    if re.match(TEMPERATURE_PATTERN, m):
        return False, 'EXPERIMENTAL_CONDITION', 'THERMAL_PARAMETER'
    # Reagent / kit
    if upper in REAGENTS:
        return False, 'REAGENT', 'LAB_REAGENT'
    # Housekeeping gene (preserve as gene but mark role)
    if upper in HOUSEKEEPING_GENES:
        return False, 'GENE_PRODUCT', 'HOUSEKEEPING_GENE'
    # Number word (low semantic value) → filter unless explicitly whitelisted
    if lower in NUMBER_WORDS:
        return True, None, None
    # Single lowercase common word of length 3-6 with no digit and not whitelisted → likely noise
    if lower == m and m.isalpha() and len(m) <= 6 and upper not in HOUSEKEEPING_GENES and upper not in WHITELIST_SHORT:
        # allow gene-like uppercase or chemistry tokens; lowercase short common gets filtered
        return True, None, None
    return False, None, None

def _hf_entities(text: str) -> List[Tuple[int,int,str,str,str]]:
    pipe = _ensure_hf_pipeline()
    if not pipe:
        return []
    spans = []
    try:
        cache_file = _hf_cache_path(text)
        outputs = None
        if cache_file and cache_file.exists():
            try:
                outputs = json.loads(cache_file.read_text(encoding='utf-8'))
            except Exception:
                outputs = None
        if outputs is None:
            outputs = pipe(text)
            if cache_file:
                try:
                    cache_file.write_text(json.dumps(outputs), encoding='utf-8')
                except Exception:
                    pass
    except Exception:
        return []
    for o in outputs:
        # HF labels often come as e.g. 'B-DISEASE' or just 'DISEASE'
        label_raw = o.get('entity_group') or o.get('entity') or ''
        label_raw = label_raw.replace('B-', '').replace('I-', '').upper()
        label_norm = LABEL_MAP.get(label_raw, label_raw)
        if FILTER_TYPES and label_norm not in FILTER_TYPES:
            continue
        start = int(o['start'])
        end = int(o['end'])
        mention = text[start:end].strip()
        if mention.upper() in BLACKLIST or mention.lower() in LOWER_BLACKLIST:
            continue
        if _is_noisy(mention):
            continue
        if len(mention) < MIN_LEN or len(mention) > MAX_LEN:
            continue
        spans.append((start, end, label_norm, mention, f'hf:{HF_MODEL_NAME}'))
    return spans


# ------------------ Merging logic ------------------

def _span_key(start: int, end: int, label: str, mention: str) -> str:
    return f'{start}:{end}:{label}:{mention.lower()}'


def merge_provider_spans(spans: List[Tuple[int,int,str,str,str]]) -> List[Tuple[int,int,str,str,str]]:
    if not MERGE_OVERLAPS:
        return spans
    # We prioritize spans based on provider order in PROVIDERS
    priority = {}
    for rank, prov in enumerate(PROVIDERS):
        priority[prov] = rank

    chosen: Dict[str, Tuple[int,int,str,str,str]] = {}
    for (s,e,label,mention,provider_full) in spans:
        provider = provider_full.split(':',1)[0]
        k_candidates = []
        # exact key
        exact_key = _span_key(s,e,label,mention)
        k_candidates.append(exact_key)
        replaced = False
        for k in k_candidates:
            if k in chosen:
                # decide by provider priority (lower rank = higher priority)
                existing = chosen[k]
                existing_provider = existing[4].split(':',1)[0]
                if priority.get(provider, 999) < priority.get(existing_provider, 999):
                    chosen[k] = (s,e,label,mention,provider_full)
                replaced = True
                break
        if not replaced:
            chosen[exact_key] = (s,e,label,mention,provider_full)
    return list(chosen.values())


def _apply_typing_overrides(label: str, mention: str, current_type: Optional[str]) -> Optional[str]:
    m_up = mention.upper()
    # Pathway detection
    if norm.is_pathway(m_up):
        return 'PATHWAY'
    # Gene symbol
    if norm.is_gene_symbol(m_up):
        return 'GENE_PRODUCT'
    # Cell types simple patterns
    if m_up.endswith(' CELLS') or m_up.endswith(' CELL') or m_up in {'T CELLS','T CELL','MACROPHAGES','MACROPHAGE','DENDRITIC CELLS','NEUTROPHILS','LYMPHOCYTES','CARDIOMYOCYTES','B LYMPHOCYTES','NK CELLS','B CELLS'}:
        return 'CELL_TYPE'
    # Microgravity environment (treat as PHENOTYPE but could become ENVIRONMENT)
    if m_up == 'MICROGRAVITY':
        return 'PHENOTYPE'
    return current_type


def extract_entities(sentences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    eid = 0
    for sent in sentences:
        text = sent['text']
        provider_spans: List[Tuple[int,int,str,str,str]] = []
        for prov in PROVIDERS:
            if prov == 'spacy':
                provider_spans.extend(_spacy_entities(text))
            elif prov == 'hf':
                provider_spans.extend(_hf_entities(text))
        merged = merge_provider_spans(provider_spans)
        # pass to filter/augment
        for (start, end, label, mention, provider_full) in merged:
            if mention.upper() in BLACKLIST or mention.lower() in LOWER_BLACKLIST:
                continue
            if norm.should_filter_span(mention):
                continue
            if len(mention) < 3 and not norm.is_gene_symbol(mention):
                continue
            sec_start_global = sent['char_start_global']
            sec_start_section = sent['char_start_section']
            node_type = schema.LABEL_TO_NODE_TYPE.get(label)
            node_type = _apply_typing_overrides(label, mention, node_type)
            if node_type is None:
                continue
            # Domain heuristics classification
            filt, override_type, role = classify_special_token(mention)
            if filt:
                continue
            if override_type:
                node_type = override_type
            preserve_case = (node_type == 'GENE_PRODUCT' or node_type == 'PATHWAY')
            canonical = norm.canonical_form(mention, preserve_case=preserve_case)
            results.append({
                'eid': eid,
                'sentence_id': sent['sid'],
                'section_index': sent['section_index'],
                'section_heading': sent['section_heading'],
                'type': label,
                'node_type': node_type,
                'mention': mention,
                'canonical': canonical,
                'provider': provider_full,
                'role': role,
                'char_start_sentence': start,
                'char_end_sentence': end,
                'char_start_section': sec_start_section + start,
                'char_end_section': sec_start_section + end,
                'char_start_global': sec_start_global + start,
                'char_end_global': sec_start_global + end
            })
            eid += 1
    return results


def _aggregate_normalized(entities: List[Dict[str, Any]]):
    by_id = {e['eid']: e for e in entities}
    # frequency & sections per canonical
    freq = {}
    for e in entities:
        freq.setdefault(e['canonical'], {'count':0,'sections':set(),'node_type':e['node_type'],'examples':[]})
        bucket = freq[e['canonical']]
        bucket['count'] += 1
        bucket['sections'].add(e['section_heading'])
        if len(bucket['examples']) < 3:
            bucket['examples'].append(e['mention'])
    normalized = []
    nid = 0
    for canon, data in freq.items():
        normalized.append({
            'nid': nid,
            'canonical': canon,
            'node_type': data['node_type'],
            'frequency': data['count'],
            'sections': sorted(list(data['sections'])),
            'examples': data['examples']
        })
        nid += 1
    return normalized


def run(base_dir: Path, pmcid: str):
    sentences = load_sentences(base_dir, pmcid)
    entities = extract_entities(sentences)
    out_dir = get_phase_dir(base_dir, pmcid, 3)
    save_jsonl(entities, out_dir / 'entities.jsonl')
    normalized = _aggregate_normalized(entities)
    save_jsonl(normalized, out_dir / 'entities.normalized.jsonl')
    return {
        'entities_raw': len(entities),
        'entities_normalized': len(normalized),
        'providers_used': [p for p in PROVIDERS]
    }


if __name__ == '__main__':  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--pmcid', required=True)
    args = ap.parse_args()
    print(run(Path(args.base), args.pmcid))
