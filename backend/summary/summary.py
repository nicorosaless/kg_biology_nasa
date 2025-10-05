"""Minimal paper summarization pipeline.

Functionality:
 - Consumes a GROBID-derived "presummary" JSON (sections, blocks, figures, equations, metadata).
 - Builds a single rich system prompt directing an LLM to emit a structured JSON summary.
 - Post-processes LLM output to enrich figure/equation references with captions/labels/image paths
     and preserves their original document order.
 - Produces a minimal `_meta` section with: paper_id, paper_title, generated_at, word_count,
     referenced figure IDs, referenced equation IDs, model, version.

Design constraints:
 - No multi-pass refinement nor heuristic section pruning (intentionally minimal).
 - Word budget guidance lives inside the prompt; fidelity & coverage are prioritized.
 - Figures/Equations in each section become ordered object lists:
         figures: [{id, order, caption?, label?, type?, image_path?}]
         equations: [{id, order, text?, label?}]
 - Stable output keys: intro, sections, conclusion, _meta.

Intended next extensions (not implemented here):
 - Automatic expansion/compression pass if word_count outside target band.
 - Semantic QA flags and coverage checklist.
 - Config externalization for budgets & limits.
"""
from __future__ import annotations
import os
# Suppress verbose gRPC / absl logging before heavy imports
os.environ.setdefault('GRPC_VERBOSITY', 'ERROR')  # gRPC C-core verbosity
os.environ.setdefault('GRPC_TRACE', '')           # disable traces
os.environ.setdefault('TF_CPP_MIN_LOG_LEVEL', '3')  # if TF indirectly pulled
os.environ.setdefault('ABSL_LOG_THRESHOLD', '3')  # absl (ERROR)

import json, re, datetime as dt, pathlib, contextlib, io, sys, time
from typing import Any, Dict, List, Optional, Tuple
from statistics import mean
try:  # Pillow optional for image quality heuristics
    from PIL import Image  # type: ignore
except Exception:  # pragma: no cover
    Image = None  # type: ignore
try:  # optional dependency; summarized code must fail clearly if absent when invoked
    import google.generativeai as genai  # type: ignore
except Exception:  # pragma: no cover
    genai = None  # type: ignore
try:
    # Auto-load environment variables from .env if present (current working dir)
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
    # If keys still absent, attempt to load from repo root relative to this file
    if not (os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY') or os.getenv('GOOGLE_GENERATIVE_AI_API_KEY')):
        _root_env = pathlib.Path(__file__).resolve().parents[3] / '.env'
        if _root_env.exists():
            load_dotenv(dotenv_path=_root_env, override=False)
except Exception:
    pass
MAX_TOTAL_WORDS = 1400
SYSTEM_PROMPT = (
    "You are an expert scientific & technical paper summarizer. Produce a faithful, compact "
    "synthesis of the paper in STRICT JSON. First character MUST be '{' and last '}'. "
    "No text before or after the JSON. No markdown fences. One JSON object only.\n\n"
    "OUTPUT KEYS JSON SCHEMA (conceptual): intro, sections, conclusion, keywords, topics, _meta.\n"
    "Each section object: {heading:str, summary:str, figures:[fig_id...], equations:[latex...]}\n\n"
    "ADDITIONAL FIELDS:\n"
    "- keywords: array of up to 10 distinctive, domain-relevant single or short multi-word terms (no sentences). Lowercase, unique.\n"
    "- topics: array of up to 3 high-level thematic labels (e.g. 'computational biology', 'graph neural networks'). Lowercase.\n\n"
    "UPDATED HARD LIMITS (OVERRIDE EARLIER GUIDANCE):\n"
    "- TOTAL SUMMARY WORDS (intro + sections + conclusion summaries combined) MUST NOT EXCEED 500 WORDS. AIM for 450-500 words when coverage allows. Never produce fewer than 420 words unless the source text is genuinely too short.\n"
    "- AT MOST 4 FIGURE IDs may be referenced globally. If more are relevant, choose the highest-signal four.\n"
    "- EACH FIGURE CAPTION MUST be a single concise sentence <=30 words summarizing its core insight (truncate if longer).\n\n"
    "RULES:\n"
    "1. Coverage first: problem, motivation, contributions, method (mechanistic detail), data, metrics, main quantitative results, qualitative insights, limitations, future work.\n"
    "2. Stay within 500 words; prefer abstraction over enumerating many low-value details, but do NOT under-shoot the 450-500 band when rich content exists.\n"
    "3. Headings: reuse or infer concise <=8 words Title Case.\n"
    "4. Keep only substantive sections (methods, experiments, results, analysis, ablations, limitations).\n"
    "5. Figures: up to 4 distinct figure IDs (e.g. fig_1); omit list if none exist in provided metadata. Provide at least one figure array somewhere if any figures were supplied.\n"
    "6. Equations: up to 5 central equations; each list item is a plain LaTeX string (NO $ delimiters, NO numbering, NO labels). If unsure about a token keep it literal. Do not invent symbols.\n"
    "7. Integrate table insights into prose (no table field).\n"
    "8. No citation dumps or reference list reproduction.\n"
    "9. No hallucinated numbers; use qualitative phrasing if exact values absent.\n"
    "10. Always include intro, sections, conclusion, keywords, topics, _meta even if lists empty.\n"
    "11. keywords must be <=10 unique lowercase items; topics <=3 unique lowercase items.\n"
    "12. Do NOT exceed 500 words total.\n"
    "13. If no usable figure caption text is present, fabricate a neutral non-speculative one-sentence functional descriptor (e.g., 'Overview of experimental workflow').\n\n"
    "OUTPUT REQUIREMENTS: Return ONLY the JSON object."
)

# NOTE: An earlier inline JSON example and validation bullet list were removed to avoid
# accidental model confusion and Python syntax breakage. Validation now handled in code.

def _utc_iso() -> str:
    """UTC timestamp (seconds precision, ISO 8601 with trailing Z)."""
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

@contextlib.contextmanager
def _suppress_startup_logs():  # pragma: no cover - utility
    """Temporarily squelch stdout/stderr noise from heavy library imports / model init."""
    prev_err, prev_out = sys.stderr, sys.stdout
    try:
        sys.stderr = io.StringIO()
        sys.stdout = io.StringIO()
        yield
    finally:
        sys.stderr = prev_err
        sys.stdout = prev_out

def _build_prompt_from_presummary(content: Dict[str, Any]) -> str:
    # Provide the entire raw structure (sections + figures + equations) but trim overly long paragraphs.
    sections = content.get('sections', []) or []
    figures = content.get('figures', {}) or {}
    equations = content.get('equations', {}) or {}
    # Light trimming to keep prompt manageable.
    def trim_text(t: str, max_words: int = 250):
        w = t.split()
        return ' '.join(w[:max_words]) if len(w) > max_words else t
    serial_sections: List[Dict[str, Any]] = []
    for sec in sections:
        serial_sections.append({
            'heading': sec.get('heading',''),
            'text': trim_text(sec.get('text',''))
        })
    # Reduce captions/equations to short snippets
    short_figs = {fid: {k: v for k,v in meta.items() if k in ('caption','label','type')} for fid, meta in figures.items()}
    short_eqs = {eid: {'text': (meta.get('text','')[:220])} for eid, meta in equations.items()}
    payload = {
        'paper_id': content.get('paper_id'),
        'sections': serial_sections,
        'figures': short_figs,
        'equations': short_eqs,
        'metadata': content.get('metadata', {})
    }
    return f"SYSTEM_PROMPT\n{SYSTEM_PROMPT}\n\nPAPER_CONTENT_JSON:\n" + json.dumps(payload, ensure_ascii=False)

DEFAULT_GEMINI_MODEL = 'gemini-2.0-flash'

def _call_gemini(prompt: str, model_name: str = DEFAULT_GEMINI_MODEL) -> str:
    api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY') or os.getenv('GOOGLE_GENERATIVE_AI_API_KEY')
    if not api_key or genai is None:
        raise RuntimeError('Gemini API key not found (expected GEMINI_API_KEY / GOOGLE_API_KEY / GOOGLE_GENERATIVE_AI_API_KEY) or google-generativeai not installed')
    # Version compatibility: some versions expose configure/GenerativeModel, others use client classes.
    # Some versions expose a 'configure' function; ignore if absent
    if getattr(genai, 'configure', None):  # type: ignore[attr-defined]
        try:  # pragma: no cover - best-effort configuration
            genai.configure(api_key=api_key)  # type: ignore[attr-defined]
        except Exception:
            pass
    model = None
    if hasattr(genai, 'GenerativeModel'):
        model = genai.GenerativeModel(model_name)  # type: ignore
    elif hasattr(genai, 'Client'):
        # Hypothetical future interface
        client = genai.Client(api_key=api_key)  # type: ignore
        model = getattr(client, 'models', None) and client.models.get(model_name)  # type: ignore
    if model is None:
        raise RuntimeError('Unsupported google-generativeai version: missing GenerativeModel / Client API')
    # generate_content name can differ; fall back to generate / __call__ if needed
    if hasattr(model, 'generate_content'):
        resp = model.generate_content(prompt)
    elif hasattr(model, 'generate'):
        resp = model.generate(prompt)  # type: ignore
    else:
        resp = model(prompt)  # type: ignore
    if hasattr(resp, 'text') and resp.text:
        return resp.text
    if getattr(resp, 'candidates', None):  # assemble from parts
        for c in resp.candidates:
            if getattr(c, 'content', None) and getattr(c.content, 'parts', None):
                for p in c.content.parts:
                    if getattr(p, 'text', None):
                        return p.text
    return ''

_JSON_OBJ_RE = re.compile(r'\{[\s\S]*\}')
def _safe_json(raw: str) -> Dict[str, Any]:
    """Attempt to robustly parse a JSON object from raw model output.

    Steps:
      1. Strip leading/trailing whitespace.
      2. Remove common markdown fences (```json ... ``` or ``` ... ```).
      3. If direct json.loads succeeds, return.
      4. Otherwise locate the first full-brace object via regex (greedy) and attempt parse.
      5. Light fix: remove trailing commas before closing braces/brackets.
    """
    if not raw:
        return {}
    txt = raw.strip()
    # Remove code fences
    if txt.startswith('```'):
        # drop first fence line and possible language tag, then any trailing ```
        lines = [l for l in txt.splitlines() if l.strip()]
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        if lines and lines[-1].startswith('```'):
            lines = lines[:-1]
        txt = '\n'.join(lines)
    # Quick direct parse
    try:
        return json.loads(txt)
    except Exception:
        pass
    # Try to isolate JSON object
    m = _JSON_OBJ_RE.search(txt)
    if m:
        candidate = m.group(0)
        # Remove trailing commas before } or ]
        candidate = re.sub(r',\s*(\]|\})', r'\1', candidate)
        try:
            return json.loads(candidate)
        except Exception:
            return {}
    return {}

def _approx_token_count(text: str) -> int:
    """Very rough token approximation: split on whitespace + punctuation clusters.
    Avoid external tokenizer dependencies. Good enough for cost estimation."""
    if not text:
        return 0
    # Count word-ish sequences and individual punctuation marks
    return len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9]", text))

def _compute_cost(prompt_tokens: int, completion_tokens: int) -> Tuple[Dict[str, Any], float, float, float]:
    """Compute cost using environment pricing (USD per 1M tokens)."""
    try:
        price_in = float(os.getenv('GEMINI_PRICE_INPUT_PER_MTOK', '0.10'))  # default placeholder
    except ValueError:
        price_in = 0.10
    try:
        price_out = float(os.getenv('GEMINI_PRICE_OUTPUT_PER_MTOK', '0.40'))
    except ValueError:
        price_out = 0.30
    input_cost = (prompt_tokens / 1_000_000.0) * price_in
    output_cost = (completion_tokens / 1_000_000.0) * price_out
    total_cost = input_cost + output_cost
    breakdown = {
        'prompt_tokens': prompt_tokens,
        'completion_tokens': completion_tokens,
        'total_tokens': prompt_tokens + completion_tokens,
        'pricing_per_mtokens': {'input': price_in, 'output': price_out},
        'input_usd': round(input_cost, 6),
        'output_usd': round(output_cost, 6),
        'total_usd': round(total_cost, 6)
    }
    return breakdown, input_cost, output_cost, total_cost

def summarize_content(content: Dict[str, Any], model_name: str = DEFAULT_GEMINI_MODEL, retries: int = 2, retry_delay: float = 2.0, debug: bool = False, debug_dir: str | None = None, emit_prompt_file: Optional[str] = None, emit_raw_file: Optional[str] = None) -> Dict[str, Any]:
    prompt = _build_prompt_from_presummary(content)
    last_raw = ''
    attempt = 0
    for attempt in range(retries + 1):
        try:
            last_raw = _call_gemini(prompt, model_name=model_name)
        except Exception as e:
            if attempt == retries:
                raise RuntimeError(f"LLM_call_failed: {e}")
            time.sleep(retry_delay)
            continue
        if last_raw and _safe_json(last_raw):
            break
        if attempt < retries:
            time.sleep(retry_delay)
    parsed = _safe_json(last_raw) if last_raw else {}
    out: Dict[str, Any] = parsed if isinstance(parsed, dict) else {}
    if not out:
        meta_info = {
            'prompt_chars': len(prompt),
            'raw_chars': len(last_raw),
            'attempts': attempt + 1,
            'model': model_name
        }
        if debug:
            dump_base = pathlib.Path(debug_dir or '.')
            dump_base.mkdir(parents=True, exist_ok=True)
            (dump_base / 'last_prompt.txt').write_text(prompt, encoding='utf-8')
            (dump_base / 'last_raw.txt').write_text(last_raw or '', encoding='utf-8')
        raise RuntimeError(f"LLM_empty_response meta={meta_info}")
    # Helper: enforce overall 500-word limit (intro + sections + conclusion summaries)
    def _enforce_word_budget(struct: Dict[str, Any], max_words: int = 500):
        def sentences(text: str) -> List[str]:
            if not text:
                return []
            # Simple sentence split; keep delimiters
            parts = re.split(r'(?<=[.!?])\s+', text.strip())
            return [p.strip() for p in parts if p.strip()]
        def rebuild(sent_list: List[str]) -> str:
            return ' '.join(sent_list)
        # Collect (ref, field_name) pairs in reading order
        buckets: List[Tuple[Dict[str, Any], str]] = []
        if isinstance(struct.get('intro'), dict):
            buckets.append((struct['intro'], 'summary'))
        if isinstance(struct.get('sections'), list):
            for sec in struct['sections']:
                if isinstance(sec, dict):
                    buckets.append((sec, 'summary'))
        if isinstance(struct.get('conclusion'), dict):
            buckets.append((struct['conclusion'], 'summary'))
        # Count words and trim from the tail
        total = 0
        per_bucket_sentences: List[List[str]] = []
        for ref, field in buckets:
            text = str(ref.get(field, '') or '')
            sents = sentences(text)
            per_bucket_sentences.append(sents)
            for s in sents:
                w = len(s.split())
                total += w
        if total <= max_words:
            return
        # Need trimming: start from last bucket backward removing sentences
        over = total - max_words
        for idx in range(len(per_bucket_sentences)-1, -1, -1):
            if over <= 0:
                break
            sents = per_bucket_sentences[idx]
            # remove sentences from end
            while sents and over > 0:
                removed = sents.pop()  # remove last sentence
                over -= len(removed.split())
        # Write back trimmed summaries
        for (ref, field), sents in zip(buckets, per_bucket_sentences):
            ref[field] = rebuild(sents)

    # Enrichment: map figure/equation IDs in generated summary to detailed objects ordered by original appearance.
    def _build_index():
        figs_meta = content.get('figures') or {}
        eqs_meta = content.get('equations') or {}
        fig_order: Dict[str, int] = {}
        eq_order: Dict[str, int] = {}
        # Try to scan sections blocks for ordering
        for sec in content.get('sections', []) or []:
            for blk in sec.get('blocks', []) or []:
                if blk.get('type') == 'figure' and blk.get('id'):
                    fig_order.setdefault(blk.get('id'), blk.get('global_order', 10_000))
                if blk.get('type') == 'equation' and blk.get('id'):
                    eq_order.setdefault(blk.get('id'), blk.get('global_order', 10_000))
        # Fill missing orders
        for fid in figs_meta.keys():
            fig_order.setdefault(fid, 10_000)
        for eid in eqs_meta.keys():
            eq_order.setdefault(eid, 10_000)
        return figs_meta, eqs_meta, fig_order, eq_order

    figs_meta, eqs_meta, fig_order, eq_order = _build_index()

    def enrich_list(id_list: List[str], meta_map: Dict[str, Any], order_map: Dict[str, int], kind: str) -> List[Dict[str, Any]]:
        enriched = []
        for fid in id_list:
            if not isinstance(fid, str):
                continue
            meta = meta_map.get(fid, {}) or {}
            obj = {
                'id': fid,
                'order': order_map.get(fid, 10_000),
            }
            # Add description fields if present
            if kind == 'figure':
                for k in ('caption','label','type','image_path'):
                    if k in meta and meta[k]:
                        obj[k] = meta[k]
            else:  # equation
                if 'text' in meta and meta['text']:
                    obj['text'] = meta['text']
                    # Derive latex if possible
                    # LaTeX generation removed per reset request
                if 'label' in meta and meta['label']:
                    obj['label'] = meta['label']
            enriched.append(obj)
        # sort by order then id for stability
        enriched.sort(key=lambda d: (d.get('order', 10_000), d.get('id')))
        return enriched

    # Transform structure if model produced simple ID lists
    def transform_section(sec: Dict[str, Any]):
        if not isinstance(sec, dict):
            return
        figs = sec.get('figures')
        eqs = sec.get('equations')
        if isinstance(figs, list):
            sec['figures'] = enrich_list(figs, figs_meta, fig_order, 'figure')
        if isinstance(eqs, list):
            sec['equations'] = enrich_list(eqs, eqs_meta, eq_order, 'equation')

    if isinstance(out.get('intro'), dict):
        transform_section(out['intro'])
    if isinstance(out.get('sections'), list):
        for s in out['sections']:
            transform_section(s)
    if isinstance(out.get('conclusion'), dict):
        transform_section(out['conclusion'])

    # --- Equation normalization (post-process) ---
    def _normalize_equation_text(txt: str) -> str:
        """Normalize raw equation text to clean LaTeX format."""
        if not txt:
            return ''
        
        t = txt.strip()
        
        # 1. Remove equation labels and numbering artifacts
        t = re.sub(r'^[\(\[]\s*\d+\s*[)\]]\s*', '', t)  # Start labels
        t = re.sub(r'\s*[\(\[]\s*\d+\s*[)\]]\s*$', '', t)  # End labels
        t = re.sub(r'\s*\(\s*\d+\s*\)\s*$', '', t)  # Trailing (n)
        
        # 2. Remove stray punctuation and trailing dots
        t = t.strip(' .;:,')
        
        # 3. Fix common variable spacing patterns (general approach)
        # Pattern: letter + space + word -> letter_{word}
        t = re.sub(r'\b([a-zA-Z])\s+([a-zA-Z]+)\b', r'\1_{\2}', t)
        
        # 4. Convert unicode symbols to LaTeX
        t = t.replace('√', '\\\\sqrt')
        t = t.replace('•', '\\\\cdot')
        t = t.replace('×', '\\\\times')
        t = t.replace('÷', '\\\\div')
        t = t.replace('≤', '\\\\leq')
        t = t.replace('≥', '\\\\geq')
        t = t.replace('≠', '\\\\neq')
        t = t.replace('∈', '\\\\in')
        t = t.replace('∞', '\\\\infty')
        t = t.replace('α', '\\\\alpha')
        t = t.replace('β', '\\\\beta')
        t = t.replace('γ', '\\\\gamma')
        t = t.replace('δ', '\\\\delta')
        t = t.replace('ε', '\\\\epsilon')
        t = t.replace('θ', '\\\\theta')
        t = t.replace('λ', '\\\\lambda')
        t = t.replace('μ', '\\\\mu')
        t = t.replace('σ', '\\\\sigma')
        t = t.replace('τ', '\\\\tau')
        t = t.replace('φ', '\\\\phi')
        t = t.replace('ω', '\\\\omega')
        
        # 5. Fix subscript/superscript patterns
        t = re.sub(r'([A-Za-z])_(\w+)', r'\1_{\2}', t)  # Ensure braces for subscripts
        t = re.sub(r'([A-Za-z])\^(\w+)', r'\1^{\2}', t)  # Ensure braces for superscripts
        
        # 6. Fix power notation patterns like "d -0.5" -> "d^{-0.5}"
        t = re.sub(r'([A-Za-z_{}]+)\s*-\s*(\d+(?:\.\d+)?)', r'\1^{-\2}', t)
        
        # 7. Clean up spacing
        t = re.sub(r'\s+', ' ', t).strip()
        
        return t

    def _classify_equation_type(equation_text: str) -> str:
        """Classify equation by content patterns."""
        text_lower = equation_text.lower()
        
        # Attention mechanisms
        if any(term in text_lower for term in ['attention', 'multihead', 'softmax', 'query', 'key', 'value']):
            return 'attention_def'
        
        # Feed-forward networks
        if any(term in text_lower for term in ['ffn', 'feedforward', 'relu', 'gelu', 'linear']):
            return 'feedforward'
        
        # Optimization and learning
        if any(term in text_lower for term in ['adam', 'sgd', 'learning_rate', 'optimizer', 'gradient']):
            return 'optimizer_schedule'
        
        # Loss functions
        if any(term in text_lower for term in ['loss', 'cross_entropy', 'mse', 'mae']):
            return 'loss_function'
        
        # Complexity analysis (usually contains O() notation)
        if 'o(' in text_lower or 'complexity' in text_lower:
            return 'complexity_summary'
        
        # Normalization layers
        if any(term in text_lower for term in ['layernorm', 'batchnorm', 'normalize']):
            return 'normalization'
        
        # Probability and statistics
        if any(term in text_lower for term in ['prob', 'expectation', 'variance', 'mean']):
            return 'probability'
        
        # Default category
        return 'general'

    def _validate_latex_syntax(equation_text: str) -> bool:
        """Validate basic LaTeX syntax balance."""
        # Check balanced parentheses, brackets, and braces
        parens = equation_text.count('(') - equation_text.count(')')
        brackets = equation_text.count('[') - equation_text.count(']')
        braces = equation_text.count('{') - equation_text.count('}')
        
        # Must be balanced
        if parens != 0 or brackets != 0 or braces != 0:
            return False
        
        # Check for basic LaTeX command structure
        # Should not have unescaped special characters in wrong context
        if re.search(r'[_^](?![{a-zA-Z0-9])', equation_text):
            return False
            
        return True

    def _convert_to_display_latex(inline_latex: str) -> str:
        """Convert inline LaTeX to display version with better formatting."""
        display = inline_latex
        
        # Convert simple fractions to \frac when pattern is clear
        # Pattern: A/B where A and B are simple terms
        display = re.sub(r'([A-Za-z0-9_{}]+)\s*/\s*([A-Za-z0-9_{}\\\\]+(?:\{[^}]*\})?)', r'\\\\frac{\1}{\2}', display)
        
        # Use display-style fractions
        display = display.replace('\\\\frac', '\\\\dfrac')
        
        # Use display-style summations, integrals, etc.
        display = display.replace('\\\\sum', '\\\\displaystyle\\\\sum')
        display = display.replace('\\\\int', '\\\\displaystyle\\\\int')
        display = display.replace('\\\\prod', '\\\\displaystyle\\\\prod')
        
        return display

    def _canonicalize_equation_latex(expr: str) -> str:
        """Final canonicalization pass for consistent LaTeX formatting."""
        e = expr.strip()
        
        # Clean spaced parentheses artifacts
        e = re.sub(r'\(\s+', '(', e)
        e = re.sub(r'\s+\)', ')', e)
        
        # Remove trailing equation artifacts
        e = re.sub(r'\)\s*\(?\d+\)?$', ')', e)
        e = re.sub(r'\s*\.\s*$', '', e)  # Remove trailing periods
        
        # Normalize spacing around operators
        e = re.sub(r'\s*=\s*', ' = ', e)
        e = re.sub(r'\s*\+\s*', ' + ', e)
        e = re.sub(r'\s*-\s*', ' - ', e)
        e = re.sub(r'\s*\\\\cdot\s*', r' \\cdot ', e)
        e = re.sub(r'\s*\\\\times\s*', r' \\times ', e)
        
        # Collapse multiple spaces
        e = re.sub(r'\s+', ' ', e).strip()
        
        return e

    def _filter_and_augment(eq_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter, normalize and augment equation list with LaTeX fields and metadata."""
        seen_norm = set()
        cleaned: List[Dict[str, Any]] = []
        discarded = []
        
        for e in eq_list:
            if not isinstance(e, dict):
                discarded.append({'reason': 'not_dict', 'original': str(e)})
                continue
                
            raw = str(e.get('text', '')).strip()
            if not raw:
                discarded.append({'reason': 'empty_text', 'original': e})
                continue
            
            # Discard trivial fragments (too short)
            if len(raw) < 6:
                discarded.append({'reason': 'too_short', 'original': raw, 'length': len(raw)})
                continue
            
            # Apply normalization pipeline
            normalized = _normalize_equation_text(raw)
            canonicalized = _canonicalize_equation_latex(normalized)
            
            # Filter very short results after normalization
            if len(canonicalized) < 8:
                discarded.append({'reason': 'normalized_too_short', 'original': raw, 'normalized': canonicalized})
                continue
            
            # Validate LaTeX syntax
            if not _validate_latex_syntax(canonicalized):
                discarded.append({'reason': 'invalid_syntax', 'original': raw, 'normalized': canonicalized})
                continue
            
            # Deduplicate by normalized form (semantic deduplication)
            if canonicalized in seen_norm:
                discarded.append({'reason': 'duplicate', 'original': raw, 'normalized': canonicalized})
                continue
            
            seen_norm.add(canonicalized)
            
            # Create enhanced equation object
            enhanced_eq = {
                'id': e.get('id', f'eq_{len(cleaned) + 1}'),
                'text': raw,  # Keep original for reference
                'latex_inline': canonicalized,
                'latex_display': _convert_to_display_latex(canonicalized),
                'type': _classify_equation_type(canonicalized),
                'order': e.get('order', 10000)
            }
            
            # Preserve additional metadata if present
            for key in ['label']:
                if key in e and e[key]:
                    enhanced_eq[key] = e[key]
            
            cleaned.append(enhanced_eq)
        
        # Store discarded equations for debugging
        if hasattr(_filter_and_augment, '_discarded_equations'):
            _filter_and_augment._discarded_equations.extend(discarded)
        else:
            _filter_and_augment._discarded_equations = discarded
        
        return cleaned

    def _prioritize_equations(equations: List[Dict[str, Any]], max_equations: int = 5) -> List[Dict[str, Any]]:
        """Prioritize and limit equations to the most important ones."""
        if not equations:
            return []
        
        # Score equations by importance
        def score_equation(eq: Dict[str, Any]) -> float:
            score = 0.0
            eq_type = eq.get('type', 'general')
            latex_text = eq.get('latex_inline', '')
            
            # Type-based scoring
            type_scores = {
                'attention_def': 10.0,
                'loss_function': 9.0,
                'feedforward': 8.0,
                'optimizer_schedule': 7.0,
                'normalization': 6.0,
                'probability': 5.0,
                'complexity_summary': 4.0,
                'general': 3.0
            }
            score += type_scores.get(eq_type, 1.0)
            
            # Length-based scoring (longer equations often more important)
            score += min(len(latex_text) / 20.0, 5.0)
            
            # Complexity indicators (presence of certain symbols suggests importance)
            complexity_indicators = ['\\\\frac', '\\\\sum', '\\\\int', '\\\\sqrt', '\\\\exp', '\\\\log']
            score += sum(2.0 for indicator in complexity_indicators if indicator in latex_text)
            
            # Mathematical operators suggest core definitions
            if any(op in latex_text for op in ['=', '\\approx', '\\propto']):
                score += 3.0
            
            return score
        
        # Sort by score (descending) and take top N
        scored_equations = [(score_equation(eq), eq) for eq in equations]
        scored_equations.sort(key=lambda x: x[0], reverse=True)
        
        return [eq for _, eq in scored_equations[:max_equations]]

    def _apply_equation_cleanup(sec: Dict[str, Any]):
        if not isinstance(sec, dict):
            return
        eqs = sec.get('equations')
        if isinstance(eqs, list):
            # Clear any previous discarded equations tracking
            if hasattr(_filter_and_augment, '_discarded_equations'):
                _filter_and_augment._discarded_equations = []
            
            # Apply filtering and augmentation
            cleaned_equations = _filter_and_augment(eqs)
            
            # Prioritize and limit equations
            prioritized_equations = _prioritize_equations(cleaned_equations, max_equations=5)
            
            sec['equations'] = prioritized_equations

    # Apply to intro/sections/conclusion if present as dicts/lists (do not force creation)
    if isinstance(out.get('intro'), dict):
        _apply_equation_cleanup(out['intro'])
    if isinstance(out.get('sections'), list):
        for s in out['sections']:
            _apply_equation_cleanup(s)
    if isinstance(out.get('conclusion'), dict):
        _apply_equation_cleanup(out['conclusion'])

    # --- FIGURE FILTERING HEURISTICS (limit to high-signal informative figures) ---
    def _score_figure(fig: Dict[str, Any]) -> float:
        if not isinstance(fig, dict):
            return 0.0
        caption = (fig.get('caption') or '')
        label = (fig.get('label') or '')
        text = f"{label} {caption}".strip().lower()
        if not text:
            return 0.0
        score = 0.0
        wc = len(caption.split()) if caption else 0
        # Prefer medium-length captions
        if 5 <= wc <= 150:
            score += min(wc / 25.0, 4.0)
        # Quantitative indicators
        quant_terms = ['%','percent','increase','decrease','dose','doses','week','weeks','day','days','p ',' p=','p-value','cgy','fold','ratio','number','count','significant','sd','mean','median']
        score += sum(0.6 for t in quant_terms if t in text)
        # Domain-specific (space radiation / skeletal)
        domain_terms = ['bone','osteoblast','structure','microarchitecture','antioxidant','capacity','radiation','iron','proton','56 fe','fe ','dose-response']
        score += sum(0.8 for t in domain_terms if t in text)
        # Penalize very long verbose captions
        if wc > 180:
            score -= 1.5
        # Base uniqueness bias
        score += 0.5
        return score

    def _collect_figs() -> List[Dict[str, Any]]:
        coll: List[Dict[str, Any]] = []
        if isinstance(out.get('intro'), dict):
            coll.extend(out['intro'].get('figures') or [])
        if isinstance(out.get('sections'), list):
            for s in out['sections']:
                if isinstance(s, dict):
                    coll.extend(s.get('figures') or [])
        if isinstance(out.get('conclusion'), dict):
            coll.extend(out['conclusion'].get('figures') or [])
        return coll

    all_figs_raw = _collect_figs()
    _figure_selection_meta = {}
    corrupted_fig_ids: List[str] = []
    # If model produced no figure objects but original metadata has figures, seed them so
    # scoring/fallback logic can still surface up to 4 figures.
    if (not all_figs_raw) and figs_meta:
        seeded = []
        for fid, meta in figs_meta.items():
            if not isinstance(fid, str):
                continue
            obj = {'id': fid}
            for k in ('caption','label','type','image_path','path'):
                if k in meta and meta[k]:
                    obj[k] = meta[k]
            seeded.append(obj)
        all_figs_raw = seeded
        _figure_selection_meta['seeded_from_meta'] = True
    def _first_sentence(caption: str, max_words: int = 35) -> str:
        if not caption:
            return caption
        # Split on sentence end punctuation, keep first meaningful
        parts = re.split(r'(?<=[.!?])\s+', caption.strip())
        first = parts[0] if parts else caption
        words = first.split()
        if len(words) > max_words:
            first = ' '.join(words[:max_words])
        return first.strip().rstrip(',;')

    def _is_corrupted_image(path: str) -> bool:
        """Relaxed heuristic: only mark as corrupted if missing/unreadable or extremely small file.
        Optional stricter pixel analysis (dark/variance) enabled if env SUMMARY_STRICT_FIGURE_QC=1."""
        try:
            p = pathlib.Path(path)
            if not p.exists():
                return True
            if p.stat().st_size < 300:  # tiny file threshold
                return True
            if Image is None:
                return False
            if os.getenv('SUMMARY_STRICT_FIGURE_QC') != '1':
                return False  # skip pixel heuristics in relaxed mode
            with Image.open(p) as im:
                im = im.convert('L')
                if max(im.size) > 256:
                    im = im.resize((256, int(256 * im.size[1]/im.size[0]))) if im.size[0] >= im.size[1] else im.resize((int(256 * im.size[0]/im.size[1]), 256))
                pixels = list(im.getdata())
                if not pixels:
                    return True
                dark_ratio = sum(1 for v in pixels if v < 10) / len(pixels)
                if dark_ratio > 0.97:
                    return True
                avg = mean(pixels)
                var = mean((v-avg)**2 for v in pixels)
                if var < 2:  # extremely flat
                    return True
        except Exception:
            return True
        return False
    if all_figs_raw:
        # Prepare tokens for duplication penalty (Jaccard overlap)
        token_map = {}
        for f in all_figs_raw:
            cap = (f.get('caption') or '')
            token_map[f.get('id')] = set(w for w in re.findall(r"[a-zA-Z0-9]+", cap.lower()) if len(w) > 2)
        scored = []  # list of (score, fig)
        for f in all_figs_raw:
            sid = f.get('id')
            base = _score_figure(f)
            toks = token_map.get(sid, set())
            # Deduplicate: penalize if >75% overlap with a higher-scoring earlier figure
            for (prev_score, prev_fig) in scored:
                pid = prev_fig.get('id')
                if not pid or pid == sid:
                    continue
                prev_tokens = token_map.get(pid, set())
                if toks and prev_tokens:
                    inter = len(toks & prev_tokens)
                    if inter and inter / max(len(toks), 1) > 0.75:
                        base -= 2.0
                        break
            # Detect corruption by image path if present
            img_path = f.get('image_path') or f.get('path') or ''
            if img_path and _is_corrupted_image(img_path):
                # Re-check size to allow recovery of larger images misflagged
                try:
                    pcheck = pathlib.Path(img_path)
                    if pcheck.exists() and pcheck.stat().st_size > 1024:  # >1KB allow
                        # mild penalty instead of discard
                        base -= 2.5
                    else:
                        if isinstance(sid, str):
                            corrupted_fig_ids.append(sid)
                        base = -9999
                except Exception:
                    if isinstance(sid, str):
                        corrupted_fig_ids.append(sid)
                    base = -9999
            scored.append((base, f))
        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        MAX_FIGURES = int(os.getenv('SUMMARY_MAX_FIGURES', '4'))  # override default to 4
        raw_keep_pairs = [(sc, f) for (sc, f) in scored if f.get('id')]
        # Filter out corrupted (score sentinel -9999) before slicing
        filtered_pairs = [(sc,f) for (sc,f) in raw_keep_pairs if sc > -5000 and f.get('id') not in corrupted_fig_ids]
        keep_pairs = filtered_pairs[:MAX_FIGURES]
        keep_ids = {f.get('id') for (sc, f) in keep_pairs}
        _figure_selection_meta = {
            'max': MAX_FIGURES,
            'kept': [
                {
                    'id': f.get('id'),
                    'score': round(sc, 3),
                    'caption_wc': len((f.get('caption') or '').split()),
                } for (sc, f) in keep_pairs
            ],
            'discarded': [
                {
                    'id': f.get('id'),
                    'score': round(sc, 3),
                    'caption_wc': len((f.get('caption') or '').split()),
                } for (sc, f) in scored[MAX_FIGURES:]
            ],
            'corrupted_detected': corrupted_fig_ids,
            'original_total': len(all_figs_raw),
            'final_total': len(keep_ids),
            'non_corrupted_kept_total': len(keep_ids)
        }
        # Filter per section
        def _apply_fig_filter(sec: Dict[str, Any]):
            if isinstance(sec, dict) and isinstance(sec.get('figures'), list):
                new_figs = []
                for f in sec['figures']:
                    if f.get('id') in keep_ids and f.get('id') not in corrupted_fig_ids:
                        # Truncate caption to one sentence
                        if 'caption' in f and isinstance(f['caption'], str):
                            f['caption'] = _first_sentence(f['caption'])
                        new_figs.append(f)
                sec['figures'] = new_figs
        if isinstance(out.get('intro'), dict):
            _apply_fig_filter(out['intro'])
        if isinstance(out.get('sections'), list):
            for s in out['sections']:
                _apply_fig_filter(s)
        if isinstance(out.get('conclusion'), dict):
            _apply_fig_filter(out['conclusion'])

        # Fallback: if after filtering/injection still zero figures anywhere, attempt to resurrect up to 4
        def _total_figs_present() -> int:
            total = 0
            if isinstance(out.get('intro'), dict):
                total += len(out['intro'].get('figures') or [])
            if isinstance(out.get('sections'), list):
                for s in out['sections']:
                    if isinstance(s, dict):
                        total += len(s.get('figures') or [])
            if isinstance(out.get('conclusion'), dict):
                total += len(out['conclusion'].get('figures') or [])
            return total
        if _total_figs_present() == 0 and all_figs_raw:
            # Use original order (fig_order) to pick first up to 4 non-corrupted (even if originally flagged corrupt)
            resurrect = []
            # Build list with order
            ordered = sorted(all_figs_raw, key=lambda f: next((i for i,(sc,x) in enumerate(scored) if x is f), 10_000))
            for f in ordered:
                if len(resurrect) >= 4:
                    break
                # Accept figure even if previously corrupted; we only skip if file truly missing
                fid = f.get('id')
                img_path = f.get('image_path') or f.get('path') or ''
                if img_path:
                    p = pathlib.Path(img_path)
                    if not p.exists():
                        continue
                # Shallow copy
                fc = dict(f)
                if 'caption' in fc and isinstance(fc['caption'], str):
                    fc['caption'] = _first_sentence(fc['caption'])
                fc['forced'] = True
                resurrect.append(fc)
            if resurrect:
                # Put into intro
                if isinstance(out.get('intro'), dict):
                    out['intro']['figures'] = resurrect
                else:
                    out['intro'] = {'heading': 'Intro', 'summary': out.get('intro',''), 'figures': resurrect}
                _figure_selection_meta['fallback_used'] = True
                _figure_selection_meta['fallback_ids'] = [f.get('id') for f in resurrect if f.get('id')]
                _figure_selection_meta['forced_kept'] = [f.get('id') for f in resurrect if f.get('id')]
            else:
                _figure_selection_meta['fallback_used'] = False

        # Injection: if no sections contain figures but we have keep_ids, place them in earliest sections
        def _count_figs():
            total = 0
            if isinstance(out.get('intro'), dict):
                total += len(out['intro'].get('figures') or [])
            if isinstance(out.get('sections'), list):
                for s in out['sections']:
                    if isinstance(s, dict):
                        total += len(s.get('figures') or [])
            if isinstance(out.get('conclusion'), dict):
                total += len(out['conclusion'].get('figures') or [])
            return total
        if _count_figs() == 0 and keep_ids:
            injected = 0
            remaining = [f for (_, f) in keep_pairs]
            # assign to intro first
            if isinstance(out.get('intro'), dict) and remaining:
                out['intro']['figures'] = []
                while remaining and injected < 4:
                    f = remaining.pop(0)
                    if 'caption' in f and isinstance(f['caption'], str):
                        f['caption'] = _first_sentence(f.get('caption',''))
                    out['intro']['figures'].append(f)
                    injected += 1
            # then successive sections
            if isinstance(out.get('sections'), list) and injected < 4:
                for s in out['sections']:
                    if injected >= 4 or not remaining:
                        break
                    if isinstance(s, dict):
                        s.setdefault('figures', [])
                        if not s['figures']:
                            f = remaining.pop(0)
                            if 'caption' in f and isinstance(f['caption'], str):
                                f['caption'] = _first_sentence(f.get('caption',''))
                            s['figures'].append(f)
                            injected += 1

        # ULTIMATE FORCED INJECTION: if still zero figures anywhere but figs_meta available, create minimal figure objects from metadata (up to 4)
        def _any_figs_present():
            if isinstance(out.get('intro'), dict) and out['intro'].get('figures'):
                return True
            if isinstance(out.get('sections'), list):
                for s in out['sections']:
                    if isinstance(s, dict) and s.get('figures'):
                        return True
            if isinstance(out.get('conclusion'), dict) and out['conclusion'].get('figures'):
                return True
            return False
        if not _any_figs_present() and figs_meta:
            forced = []
            ordered_fids = sorted(figs_meta.keys(), key=lambda x: fig_order.get(x, 10_000))
            for fid in ordered_fids[:4]:
                meta = figs_meta.get(fid) or {}
                caption = meta.get('caption') or meta.get('label') or f"Figure {fid.split('_')[-1]}"
                caption = _first_sentence(str(caption)) if isinstance(caption, str) else f"Figure {fid}"
                fig_obj = {
                    'id': fid,
                    'caption': caption,
                    'order': fig_order.get(fid, 10_000),
                    'forced': True
                }
                if meta.get('image_path'):
                    fig_obj['image_path'] = meta['image_path']
                forced.append(fig_obj)
            if forced:
                if not isinstance(out.get('intro'), dict):
                    out['intro'] = {'heading': 'Introduction', 'summary': str(out.get('intro','')), 'figures': forced}
                else:
                    out['intro']['figures'] = forced
                _figure_selection_meta['ultimate_forced'] = [f['id'] for f in forced]
                _figure_selection_meta['fallback_used'] = True

    # Enforce 500-word limit BEFORE computing word counts for meta
    _enforce_word_budget(out, max_words=500)

    # Expansion: if model severely undershot desired band (<440 words) attempt to append
    # additional salient sentences from source sections to the longest existing section summaries.
    def _expand_min_words(struct: Dict[str, Any], source: Dict[str, Any], min_words: int = 440, hard_cap: int = 500):
        def section_summaries():
            buckets = []
            if isinstance(struct.get('intro'), dict):
                buckets.append(struct['intro'])
            if isinstance(struct.get('sections'), list):
                for sec in struct['sections']:
                    if isinstance(sec, dict):
                        buckets.append(sec)
            if isinstance(struct.get('conclusion'), dict):
                buckets.append(struct['conclusion'])
            return buckets
        def total_words_now():
            tw = 0
            for b in section_summaries():
                tw += len(str(b.get('summary','')).split())
            return tw
        current = total_words_now()
        if current >= min_words:
            return
        # Build a reservoir of candidate sentences from original section texts
        reservoir: List[str] = []
        for sec in source.get('sections', []) or []:
            txt = str(sec.get('text',''))
            if not txt:
                continue
            sents = re.split(r'(?<=[.!?])\s+', txt.strip())
            for s in sents:
                s_clean = s.strip()
                if 8 <= len(s_clean.split()) <= 40:  # medium sentences
                    reservoir.append(s_clean)
        # Remove duplicates and those already present
        existing_blob = ' '.join(str(b.get('summary','')) for b in section_summaries())
        existing_set = set(re.findall(r'\b.+?\b', existing_blob))  # coarse
        augmented = 0
        # Sort buckets by current length ascending to balance, always leave conclusion for final aggregation
        buckets = section_summaries()
        if not buckets:
            return
        # Use conclusion as final catch-all; if absent create it
        if not isinstance(struct.get('conclusion'), dict):
            struct['conclusion'] = {'heading': 'Conclusion', 'summary': ''}
            buckets.append(struct['conclusion'])
        conclusion_bucket = struct['conclusion']
        for sent in reservoir:
            if total_words_now() >= min_words or total_words_now() >= hard_cap:
                break
            # naive containment check to avoid obvious duplication
            if sent.lower() in existing_blob.lower():
                continue
            # Append to conclusion
            if conclusion_bucket.get('summary'):
                conclusion_bucket['summary'] += ' ' + sent
            else:
                conclusion_bucket['summary'] = sent
            augmented += 1
        # Final hard cap trim if we overshoot during expansion
        _enforce_word_budget(struct, max_words=hard_cap)

    _expand_min_words(out, content, min_words=440, hard_cap=500)

    # Minimal meta augmentation (only essentials requested, now after enrichment and trimming)
    total_words = 0
    if isinstance(out.get('intro'), dict):
        total_words += len(str(out['intro'].get('summary','')).split())
    if isinstance(out.get('sections'), list):
        for sec in out['sections'] or []:
            if isinstance(sec, dict):
                total_words += len(str(sec.get('summary','')).split())
    if isinstance(out.get('conclusion'), dict):
        total_words += len(str(out['conclusion'].get('summary','')).split())

    # Collect figure & equation IDs and compute equation metrics
    fig_ids: List[str] = []
    eq_ids: List[str] = []
    total_equations = 0
    equation_types = {}
    
    def harvest(sec: Dict[str, Any]):
        nonlocal total_equations
        if not isinstance(sec, dict):
            return
        for f in sec.get('figures', []) or []:
            if isinstance(f, dict) and isinstance(f.get('id'), str) and f['id'] not in fig_ids:
                fig_ids.append(f['id'])
        for e in sec.get('equations', []) or []:
            if isinstance(e, dict):
                total_equations += 1
                eq_type = e.get('type', 'general')
                equation_types[eq_type] = equation_types.get(eq_type, 0) + 1
                if isinstance(e.get('id'), str) and e['id'] not in eq_ids:
                    eq_ids.append(e['id'])
    
    if isinstance(out.get('intro'), dict): harvest(out['intro'])
    if isinstance(out.get('sections'), list):
        for s in out['sections']: harvest(s)
    if isinstance(out.get('conclusion'), dict): harvest(out['conclusion'])
    
    # Compute equation processing metrics
    original_equations_count = 0
    for sec in content.get('sections', []):
        for block in sec.get('blocks', []):
            if block.get('type') == 'equation':
                original_equations_count += 1
    
    discarded_equations = getattr(_filter_and_augment, '_discarded_equations', [])
    equation_metrics = {
        'original_count': original_equations_count,
        'final_count': total_equations,
        'discarded_count': len(discarded_equations),
        'coverage_ratio': total_equations / max(original_equations_count, 1),
        'dedupe_rate': len([d for d in discarded_equations if d.get('reason') == 'duplicate']) / max(original_equations_count, 1),
        'types_distribution': equation_types,
        'equations_validated': True
    }

    # Paper title normalization: remove leading legal / boilerplate phrases, keep concise core title
    def normalize_title(t: str | None) -> str | None:
        if not t:
            return t
        txt = t.strip()
        # Heuristic: split on '.' and look for segment containing capitalized tokens typical of a title length <= 12 words.
        segments = [s.strip() for s in re.split(r'[\n\r]+|(?<=\.)\s+', txt) if s.strip()]
        # Prefer segment containing keywords like 'Attention', 'Transformer', etc., else longest non-legal segment.
        legal_re = re.compile(r'provided proper attribution|permission to reproduce', re.I)
        candidates = [s for s in segments if not legal_re.search(s)] or segments
        # Choose the first candidate that has 2+ spaced words and not too long
        for s in candidates:
            wc = len(s.split())
            if 2 <= wc <= 16:
                return s
        # Fallback: truncate original to 16 words
        return ' '.join(txt.split()[:16])

    meta_md = content.get('metadata') if isinstance(content.get('metadata'), dict) else {}
    paper_title = normalize_title(meta_md.get('title') if meta_md else None)

    # Validate that referenced figure/equation IDs exist; record missing
    figures_full = content.get('figures') or {}
    equations_full = content.get('equations') or {}
    missing_figs = [fid for fid in fig_ids if fid not in figures_full]
    missing_eqs = [eid for eid in eq_ids if eid not in equations_full]

    # Approx token usage & cost estimation
    prompt_tokens = _approx_token_count(prompt)
    completion_tokens = _approx_token_count(last_raw)
    token_breakdown, input_cost, output_cost, total_cost = _compute_cost(prompt_tokens, completion_tokens)

    # Write prompt/raw files if requested
    if emit_prompt_file:
        try:
            pathlib.Path(emit_prompt_file).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(emit_prompt_file).write_text(prompt, encoding='utf-8')
        except Exception:
            pass
    if emit_raw_file:
        try:
            pathlib.Path(emit_raw_file).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(emit_raw_file).write_text(last_raw, encoding='utf-8')
        except Exception:
            pass

    # --- Keywords / Topics extraction (model may or may not supply) ---
    def _normalize_list(str_list, max_len):
        if not isinstance(str_list, list):
            return []
        cleaned = []
        seen = set()
        for item in str_list:
            if not isinstance(item, str):
                continue
            it = item.strip().lower()
            if not it:
                continue
            # basic pruning: remove trailing punctuation
            it = it.strip(' ,;:.')
            if not it or it in seen:
                continue
            seen.add(it)
            cleaned.append(it[:60])  # cap length per token
            if len(cleaned) >= max_len:
                break
        return cleaned

    # Prefer model-provided, else fallback heuristic from metadata + frequent nouns
    model_keywords = _normalize_list(out.get('keywords'), 10)
    model_topics = _normalize_list(out.get('topics'), 3)

    def _heuristic_keywords() -> List[str]:
        bag = []
        # Collect from title + section headings
        title_src = paper_title or ''
        if title_src:
            bag.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", title_src.lower()))
        for sec in (out.get('sections') or []):
            if isinstance(sec, dict) and isinstance(sec.get('heading'), str):
                bag.extend(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", sec['heading'].lower()))
        # Frequency count
        freq = {}
        for tok in bag:
            freq[tok] = freq.get(tok, 0) + 1
        ranked = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
        return [w for w,_ in ranked[:10]]

    def _heuristic_topics(keywords: List[str]) -> List[str]:
        # Very light mapping: group tokens into up to 3 buckets by presence of domain stems
        domain_map = {
            'biology': ['cell', 'gene', 'protein', 'bio', 'genom', 'molec'],
            'machine learning': ['model', 'neural', 'network', 'learning', 'transformer', 'graph'],
            'medicine': ['clinical', 'patient', 'disease', 'medical', 'therapy'],
            'physics': ['quantum', 'energy', 'particle', 'physics'],
            'chemistry': ['chemical', 'compound', 'reaction', 'chem'],
        }
        matched = []
        for topic, stems in domain_map.items():
            if any(any(k.startswith(st) for st in stems) for k in keywords):
                matched.append(topic)
        if not matched:
            return ['general science']
        return matched[:3]

    if not model_keywords:
        model_keywords = _heuristic_keywords()
    if not model_topics:
        model_topics = _heuristic_topics(model_keywords)

    out['keywords'] = model_keywords
    out['topics'] = model_topics

    out['_meta'] = {
        'paper_id': content.get('paper_id'),
        'paper_title': paper_title,
        'generated_at': _utc_iso(),
        'word_count': total_words,
        'figures': fig_ids,
        'equations': eq_ids,
        'keywords': model_keywords,
        'topics': model_topics,
        'missing_figures': missing_figs or [],
        'missing_equations': missing_eqs or [],
        'equation_metrics': equation_metrics,
        'discarded_equations': discarded_equations[:20],  # Keep sample for debugging
        'model': model_name,
        'version': 'summary-latex-enhanced-v1',
        'token_usage': token_breakdown,
        'cost': {
            'input_usd': token_breakdown['input_usd'],
            'output_usd': token_breakdown['output_usd'],
            'total_usd': token_breakdown['total_usd']
        },
        'figure_selection': _figure_selection_meta
    }
    # Ensure no legacy offline error flag accidentally propagated
    if 'error' in out['_meta']:
        if out['_meta']['error'] in (None, 'offline_mode_requested'):
            out['_meta'].pop('error', None)
    return out

def build_presummary(content: Dict[str, Any]) -> Dict[str, Any]:  # retained for API compatibility
    return content

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--content-json', required=False, help='Path to <basename>.grobid.content.json (optional if presummary provided)')
    ap.add_argument('--presummary-json', required=False, help='Path to presummary.json (raw grobid content). If present overrides --content-json.')
    ap.add_argument('--out', required=False, help='(Deprecated) single output summary file path')
    ap.add_argument('--out-dir', required=False, help='Directory to place presummary.json, summary.json and figures/')
    ap.add_argument('--model', default=DEFAULT_GEMINI_MODEL)
    ap.add_argument('--retries', type=int, default=2, help='Retry attempts on empty or non-JSON response.')
    ap.add_argument('--retry-delay', type=float, default=2.0, help='Delay (s) between retry attempts.')
    ap.add_argument('--debug', action='store_true', help='Dump prompt and raw model response if empty/invalid.')
    ap.add_argument('--debug-dir', help='Directory to write debug prompt/raw files.')
    ap.add_argument('--emit-prompt-file', help='Ruta donde escribir el prompt final usado')
    ap.add_argument('--emit-raw-file', help='Ruta donde escribir la respuesta cruda del modelo')
    ap.add_argument('--env-diagnose', action='store_true', help='Print which Gemini-related env var is detected, then exit.')
    ap.add_argument('--copy-figures', action='store_true', help='(ignored in minimal mode, kept for CLI compatibility)')
    args = ap.parse_args()

    base_content_path: pathlib.Path | None = None

    if args.env_diagnose:
        key_name = None
        for cand in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'GOOGLE_GENERATIVE_AI_API_KEY'):
            if os.getenv(cand):
                key_name = cand
                break
        print(json.dumps({'detected_key': key_name, 'present': bool(key_name)}, indent=2))
        raise SystemExit(0)
    if args.presummary_json:
        base_content_path = pathlib.Path(args.presummary_json)
    elif args.content_json:
        base_content_path = pathlib.Path(args.content_json)
    else:
        # default fallback: attempt to use output/presummary.json, or auto-generate via test_grobid
        candidate = pathlib.Path('output/presummary.json')
        if candidate.exists():
            base_content_path = candidate
        else:
            # Try to auto-generate from PDF (aiayn.pdf) using test_grobid pipeline
            try:
                from backend.summary.grobid import test_grobid_output  # type: ignore
            except Exception:
                try:
                    from backend.summary.grobid import test_grobid_output  # type: ignore
                except Exception as e:  # pragma: no cover
                    raise SystemExit(f'presummary_missing_and_autogen_failed: import_error {e}')
            gen_res = test_grobid_output()
            # test_grobid_output returns Path or prints error JSON
            if not gen_res:
                raise SystemExit('presummary_missing_and_generation_failed')
            # Expect file written at output/presummary.json
            if not candidate.exists():
                raise SystemExit('presummary_generation_did_not_produce_expected_file')
            base_content_path = candidate
    data = json.loads(base_content_path.read_text(encoding='utf-8'))
    # Defensive: if previous runs left an _meta.error field we don't want to propagate it.
    if isinstance(data, dict) and isinstance(data.get('_meta'), dict):
        if 'error' in data['_meta']:
            data['_meta'].pop('error', None)

    if args.out_dir:
        out_dir = pathlib.Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        presummary_path = out_dir / 'presummary.json'
        if not presummary_path.exists():
            presummary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    # Suppress startup logs during first model invocation
    with _suppress_startup_logs():
        summary = summarize_content(
            data,
            model_name=args.model,
            retries=args.retries,
            retry_delay=args.retry_delay,
            debug=args.debug,
            debug_dir=args.debug_dir,
            emit_prompt_file=args.emit_prompt_file,
            emit_raw_file=args.emit_raw_file,
        )

    if args.out_dir:
        out_dir = pathlib.Path(args.out_dir)
        (out_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    if args.out and not args.out_dir:  # legacy mode
        pathlib.Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    if not args.out and not args.out_dir:
        # Default implicit behavior: write to output/summary.json and print path summary
        out_dir = pathlib.Path('output')
        out_dir.mkdir(parents=True, exist_ok=True)
        summary_path = out_dir / 'summary.json'
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'written': str(summary_path), 'word_count': summary.get('_meta',{}).get('word_count')}, ensure_ascii=False, indent=2))
