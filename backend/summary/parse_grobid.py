"""TEI (GROBID) -> minimal internal JSON conversion.

Goal: extract structured text + figures/tables + equations with stable lightweight
localization for later layers (LLM, UI). Secondary heavy logic removed (raw tree,
complex classification, heavy heuristics). Keep code short, explicit and readable.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import datetime as dt
import xml.etree.ElementTree as ET
import re
from typing import Dict, List, Any, Optional, Tuple

TEI_NS = { 'tei': 'http://www.tei-c.org/ns/1.0' }

###############################################################################
# Helpers
###############################################################################

def _text(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"

# ----------------------------------------------------------------------------
# Core extraction functions
# ----------------------------------------------------------------------------

def _normalize_author(name: str) -> str:
    name = re.sub(r'(?<=[a-záéíóúñçü])(?=[A-Z])', ' ', name)
    return re.sub(r'\s+', ' ', name).strip()

def extract_metadata(root: ET.Element) -> Dict[str, Any]:
    title = _text(root.find('.//tei:titleStmt/tei:title', TEI_NS))
    abstract = _text(root.find('.//tei:profileDesc/tei:abstract', TEI_NS))

    authors: List[str] = []
    # Prefer author persName under titleStmt/author if present, else sourceDesc
    for path in ['.//tei:titleStmt//tei:author//tei:persName', './/tei:sourceDesc//tei:author//tei:persName']:
        for pers in root.findall(path, TEI_NS):
            full = _text(pers)
            if full:
                norm = _normalize_author(full)
                if norm not in authors:
                    authors.append(norm)

    affiliations: List[str] = []
    # Standard affiliations
    for aff in root.findall('.//tei:profileDesc//tei:affiliation', TEI_NS):
        txt = _text(aff)
        if txt:
            txt = re.sub(r'\s+', ' ', txt).strip()
            if txt not in affiliations:
                affiliations.append(txt)
    # Raw affiliation notes (type="raw_affiliation")
    for note in root.findall('.//tei:note[@type="raw_affiliation"]', TEI_NS):
        txt = _text(note)
        if txt:
            txt = re.sub(r'\s+', ' ', txt).strip()
            if txt not in affiliations:
                affiliations.append(txt)

    return {
        'title': title,
        'abstract': abstract,
        'authors': authors,
        'affiliations': affiliations,
    }

HEADING_NUM_PREFIX = re.compile(r'^\s*(\d+(?:\.\d+)*)[)\.\-:\s]+', re.U)
def _clean_heading(h: str) -> str:
    h2 = HEADING_NUM_PREFIX.sub('', h).strip()
    return h2.title() if h2.isupper() and len(h2) > 3 else h2

def extract_sections(root: ET.Element) -> List[Dict[str, Any]]:
    body = root.find('.//tei:text/tei:body', TEI_NS)
    sections: List[Dict[str, Any]] = []
    if body is None:
        return sections
    top_divs = body.findall('./tei:div', TEI_NS)
    for div in top_divs:
        head = div.find('tei:head', TEI_NS)
        head_text = _text(head)
        if head_text:
            head_text = _clean_heading(head_text)
        blocks: List[Dict[str, Any]] = []
        paras: List[str] = []
        def push_paragraph(t: str):
            idx = len(blocks)
            blocks.append({'type': 'paragraph', 'text': t, 'block_index': idx})
            paras.append(t)
        # Iterate children preserving order (one nesting level flatten)
        for child in list(div):
            tag = child.tag.split('}')[-1]
            if tag == 'p':
                tx = _text(child)
                if tx:
                    push_paragraph(tx)
            elif tag == 'figure':
                idx = len(blocks)
                blocks.append({'type': 'figure', 'block_index': idx})
            elif tag == 'formula':
                tx = _text(child)
                if tx:
                    idx = len(blocks)
                    blocks.append({'type': 'equation', 'text': tx[:800], 'block_index': idx})
            elif tag == 'div':
                for sub in list(child):
                    stag = sub.tag.split('}')[-1]
                    if stag == 'p':
                        tx = _text(sub)
                        if tx:
                            push_paragraph(tx)
                    elif stag == 'figure':
                        idx = len(blocks); blocks.append({'type': 'figure', 'block_index': idx})
                    elif stag == 'formula':
                        tx = _text(sub)
                        if tx:
                            blocks.append({'type': 'equation', 'text': tx[:800], 'block_index': len(blocks)})
        if not head_text and paras:
            synthetic = ' '.join(paras[0].split()[:5])
            head_text = f"(untitled) {synthetic}" if synthetic else '(untitled)'
        if head_text and paras:
            sections.append({
                'heading': head_text,
                'paragraphs': paras,
                'text': '\n'.join(paras),
                'blocks': blocks
            })
    # Abstract synthetic
    abstract_elem = root.find('.//tei:profileDesc/tei:abstract', TEI_NS)
    if abstract_elem is not None:
        abs_text = _text(abstract_elem)
        if abs_text and (not sections or 'abstract' not in sections[0]['heading'].lower()):
            sections.insert(0, {
                'heading': 'Abstract',
                'paragraphs': [abs_text],
                'text': abs_text,
                'blocks': [{'type': 'paragraph', 'text': abs_text, 'block_index': 0}]
            })
    # Headless body paragraphs
    headless = []
    for p in body.findall('./tei:p', TEI_NS):
        tx = _text(p)
        if tx:
            headless.append(tx)
    if headless:
        sections.insert(0, {
            'heading': 'Preface',
            'paragraphs': headless,
            'text': '\n'.join(headless),
            'blocks': [{'type': 'paragraph', 'text': t, 'block_index': i} for i, t in enumerate(headless)]
        })
    return sections

def _parse_coords(raw: Optional[str]) -> Tuple[Optional[str], Optional[List[Dict[str, float]]], Optional[Dict[str, float]]]:
    """Devuelve (coords_raw, groups, bbox) usando el primer page como referencia."""
    raw = (raw or '').strip()
    if not raw:
        return None, None, None
    groups = []
    union = None
    for part in raw.split(';'):
        pieces = [p.strip() for p in part.split(',') if p.strip()]
        if len(pieces) != 5:
            continue
        try:
            page = int(float(pieces[0]))
            x, y, w, h = map(lambda v: float(v), pieces[1:])
        except ValueError:
            continue
        x2, y2 = x + w, y + h
        groups.append({'page': page, 'x': x, 'y': y, 'w': w, 'h': h, 'x2': x2, 'y2': y2})
        if union is None:
            union = (page, x, y, x2, y2)
        elif page == union[0]:
            pg, ux1, uy1, ux2, uy2 = union
            union = (pg, min(ux1, x), min(uy1, y), max(ux2, x2), max(uy2, y2))
    bbox = None
    if union is not None:
        pg, x1, y1, x2, y2 = union
        bbox = {'page': pg, 'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, 'width': x2 - x1, 'height': y2 - y1}
    return raw or None, (groups or None), bbox

def extract_figures_tables(root: ET.Element) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for idx, fig in enumerate(root.findall('.//tei:figure', TEI_NS), start=1):
        head = fig.find('tei:head', TEI_NS)
        label_el = head.find('tei:label', TEI_NS) if head is not None else None
        caption_el = fig.find('tei:figDesc', TEI_NS) or (head.find('tei:desc', TEI_NS) if head is not None else None)
        table_struct = None
        if (fig.get('type') or '').lower() == 'table':
            table_el = fig.find('.//tei:table', TEI_NS)
            if table_el is not None:
                rows = [[_text(c) for c in row.findall('tei:cell', TEI_NS)] for row in table_el.findall('.//tei:row', TEI_NS)]
                rows = [r for r in rows if any(r)]
                if rows:
                    table_struct = {'rows': rows, 'row_count': len(rows), 'col_count': max(len(r) for r in rows)}
        coords_raw, groups, bbox = _parse_coords(fig.get('coords'))
        result[f'fig_{idx}'] = {
            'label': _text(label_el) or _text(head),
            'caption': _text(caption_el) or _text(head),
            'type': fig.get('type') or 'figure',
            'table': table_struct,
            'coords_raw': coords_raw,
            'coords_groups': groups,
            'bbox': bbox
        }
    return result

def extract_equations(root: ET.Element) -> Dict[str, Dict[str, Any]]:
    eqs: Dict[str, Dict[str, Any]] = {}
    for idx, formula in enumerate(root.findall('.//tei:formula', TEI_NS), start=1):
        content = _text(formula)
        if not content:
            continue
        label = _text(formula.find('tei:label', TEI_NS))
        coords_raw, groups, bbox = _parse_coords(formula.get('coords'))
        eqs[f'eq_{idx}'] = {
            'label': label,
            'text': content[:800],
            'coords_raw': coords_raw,
            'coords_groups': groups,
            'bbox': bbox,
            'page': bbox.get('page') if bbox else None
        }
    return eqs

def extract_references(root: ET.Element) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for bibl in root.findall('.//tei:listBibl/tei:biblStruct', TEI_NS):
        title = _text(bibl.find('.//tei:title', TEI_NS))
        authors = []
        for pers in bibl.findall('.//tei:author//tei:persName', TEI_NS):
            nm = _normalize_author(_text(pers))
            if nm:
                authors.append(nm)
        date = _text(bibl.find('.//tei:date', TEI_NS))
        raw = _text(bibl)
        refs.append({
            'title': title,
            'authors': authors,
            'date': date,
            'raw': raw
        })
    return refs

def extract_footnotes(root: ET.Element) -> List[Dict[str, Any]]:
    notes: List[Dict[str, Any]] = []
    for note in root.findall('.//tei:note[@place="foot"]', TEI_NS):
        notes.append({
            'id': note.get('{http://www.w3.org/XML/1998/namespace}id') or note.get('xml:id'),
            'n': note.get('n'),
            'text': _text(note)
        })
    return notes

###############################################################################
# Public API principal
###############################################################################

# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

def tei_to_content_json(pdf_path: Path, tei_xml: str) -> Dict[str, Any]:
    root = ET.fromstring(tei_xml)
    metadata = extract_metadata(root)
    sections = extract_sections(root)
    figures = extract_figures_tables(root)
    # Separate tables for convenience (figures with type=table)
    tables = {k: v for k, v in figures.items() if v.get('type') == 'table'}
    pure_figures = {k: v for k, v in figures.items() if v.get('type') != 'table'}
    equations = extract_equations(root)
    references = extract_references(root)
    footnotes = extract_footnotes(root)

    paper_id = _hash_file(pdf_path)

    # Plain full text (useful for LLM context window)
    full_text = '\n\n'.join(s.get('text','') for s in sections if s.get('text'))

    # ------------------------------------------------------------------
    # Map each figure/table/equation to the section in which it appears
    # We iterate TEI again ensuring order alignment with previously assigned ids.
    # Figures were numbered in document order in extract_figures_tables; same for equations.
    # We compute an offset because we may have inserted synthetic sections (Prefacio, Abstract)
    # before the top-level body divs.
    body = root.find('.//tei:text/tei:body', TEI_NS)
    if body is not None:
        top_divs = body.findall('./tei:div', TEI_NS)
    else:
        top_divs = []
    # Count leading synthetic sections
    synthetic_offset = 0
    for s in sections:
        if s.get('heading') in ('Prefacio', 'Abstract'):
            synthetic_offset += 1
        else:
            break
    # Helper to resolve section index for an element by searching containing top-level div
    def _resolve_section_index(elem: ET.Element) -> int:
        for idx, d in enumerate(top_divs):
            # membership test via any identity in iteration
            for e in d.iter():
                if e is elem:
                    return idx + synthetic_offset
        # Fallback: place in first section if cannot locate
        return 0
    # Map pure figures/tables to sections and blocks
    fig_counter = 1
    for fig_el in root.findall('.//tei:figure', TEI_NS):
        fig_id = f'fig_{fig_counter}'
        target_dict = None
        if fig_id in pure_figures:
            target_dict = pure_figures[fig_id]
        elif fig_id in tables:
            target_dict = tables[fig_id]
        if target_dict is not None:
            sec_idx = _resolve_section_index(fig_el)
            if 0 <= sec_idx < len(sections):
                target_dict['section_index'] = sec_idx
                target_dict['section_heading'] = sections[sec_idx].get('heading')
                # Assign id to first figure block without id
                for blk in sections[sec_idx].get('blocks', []):
                    if blk.get('type') == 'figure' and 'id' not in blk:
                        blk['id'] = fig_id
                        break
            else:
                target_dict['section_index'] = None
                target_dict['section_heading'] = None
        fig_counter += 1
    # Annotate equations
    eq_counter = 1
    for eq_el in root.findall('.//tei:formula', TEI_NS):
        eq_id = f'eq_{eq_counter}'
        if eq_id in equations:
            sec_idx = _resolve_section_index(eq_el)
            if 0 <= sec_idx < len(sections):
                equations[eq_id]['section_index'] = sec_idx
                equations[eq_id]['section_heading'] = sections[sec_idx].get('heading')
                for blk in sections[sec_idx].get('blocks', []):
                    if blk.get('type') == 'equation' and 'id' not in blk:
                        blk['id'] = eq_id
                        break
            else:
                equations[eq_id]['section_index'] = None
                equations[eq_id]['section_heading'] = None
        eq_counter += 1

    # Assign contiguous global_order
    global_order = 0
    for s_idx, sec in enumerate(sections):
        for blk in sec.get('blocks', []):
            blk['section_index'] = s_idx
            blk['global_order'] = global_order
            if blk.get('type') == 'paragraph' and 'id' not in blk:
                blk['id'] = f"p_{s_idx+1}_{blk['block_index']+1}"
            global_order += 1

    # Ensure each figure has a block placeholder
    for fig_id, meta in list(pure_figures.items()) + list(tables.items()):
        sec_idx = meta.get('section_index')
        if sec_idx is None or sec_idx >= len(sections):
            continue
        sec_blocks = sections[sec_idx].get('blocks', [])
        found = any(b.get('id') == fig_id for b in sec_blocks)
        if not found:
            # Append placeholder block
            new_index = len(sec_blocks)
            placeholder = {
                'type': 'figure' if fig_id in pure_figures else 'figure',  # keep uniform, table detail lives in tables map
                'id': fig_id,
                'block_index': new_index,
                'section_index': sec_idx
            }
            sec_blocks.append(placeholder)
            sections[sec_idx]['blocks'] = sec_blocks
    # Recalculate final global_order
    new_order = 0
    for s_idx, sec in enumerate(sections):
        for blk in sec.get('blocks', []):
            blk['section_index'] = s_idx
            blk['global_order'] = new_order
            # Guarantee id for paragraphs
            if blk.get('type') == 'paragraph' and 'id' not in blk:
                blk['id'] = f"p_{s_idx+1}_{blk['block_index']+1}"
            new_order += 1

    # Sync localization metadata figure / equation
    for s in sections:
        for blk in s.get('blocks', []):
            if blk.get('type') == 'figure' and blk.get('id'):
                fid = blk['id']
                meta = pure_figures.get(fid) or tables.get(fid)
                if meta is not None:
                    meta['block_index'] = blk.get('block_index')
                    meta['block_global_order'] = blk.get('global_order')
                    meta['section_index'] = blk.get('section_index')
            if blk.get('type') == 'equation' and blk.get('id'):
                eid = blk['id']
                meta_eq = equations.get(eid)
                if meta_eq is not None:
                    meta_eq['block_index'] = blk.get('block_index')
                    meta_eq['block_global_order'] = blk.get('global_order')
                    meta_eq['section_index'] = blk.get('section_index')

    # Lightweight synthetic detection: "Figure X:" first match in paragraph
    cap_rx = re.compile(r'(Figure|Fig\.?)[ ]+(\d+)\s*:\s*')
    existing_numbers = {int(k.split('_')[1]) for k in pure_figures if k.split('_')[1].isdigit()}
    for sec_idx, sec in enumerate(sections):
        for blk in sec.get('blocks', []):
            if blk.get('type') != 'paragraph':
                continue
            txt = blk.get('text','')
            m = cap_rx.search(txt)
            if not m:
                continue
            try:
                num = int(m.group(2))
            except ValueError:
                continue
            if num in existing_numbers:
                continue
            caption = txt[m.end():].strip()
            fid = f'fig_{num}'
            pure_figures[fid] = {
                'label': f'{m.group(1)} {num}',
                'caption': caption,
                'type': 'figure',
                'table': None,
                'synthetic': True,
                'section_index': sec_idx,
                'section_heading': sec.get('heading'),
                'block_index': blk.get('block_index'),
                'block_global_order': blk.get('global_order')
            }
            existing_numbers.add(num)

    content = {
        'paper_id': paper_id,
        'metadata': metadata,
        'sections': sections,
        'figures': pure_figures,
        'tables': tables,
        'equations': equations,
        'references': references,
        'footnotes': footnotes,
        'full_text': full_text,
        'stats': {
            'section_count': len(sections),
            # figure_count now counts all pure figures including synthetic (non-table)
            'figure_count': len(pure_figures),
            'figure_count_original': sum(1 for v in pure_figures.values() if not v.get('synthetic')),
            'figure_count_synthetic': sum(1 for v in pure_figures.values() if v.get('synthetic')),
            'table_count': len(tables),
            'equation_count': len(equations),
            'reference_count': len(references),
            'footnote_count': len(footnotes),
            'extracted_at': dt.datetime.utcnow().isoformat() + 'Z'
        }
    }
    return content


def save_content_json(pdf_path: Path, tei_xml: str, out_dir: Optional[Path] = None) -> Path:
    if out_dir is None:
        out_dir = pdf_path.parent
    content = tei_to_content_json(pdf_path, tei_xml)
    out_path = out_dir / (pdf_path.stem + '.grobid.content.json')
    out_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
    return out_path

###############################################################################
# Very simple skeleton (placeholders only) – keeps basic compatibility
###############################################################################

def build_summary_skeleton(content: Dict[str, Any]) -> Dict[str, Any]:
    secs = content.get('sections', [])
    if not secs:
        return {'intro': {'summary': '', 'figures': {}, 'equations': {}, 'word_count': 0}}
    intro = secs[0]
    conclusion = secs[-1] if len(secs) > 2 else secs[0]
    middle = secs[1:-1] if len(secs) > 2 else []
    middle = middle[:4]  # limit
    sk: Dict[str, Any] = {}
    def _entry(s):
        t = s.get('text','')
        return {'summary': '', 'figures': {}, 'equations': {}, 'word_count': len(t.split())}
    sk['intro'] = _entry(intro)
    for i, m in enumerate(middle, start=1):
        sk[f'section_{i}'] = _entry(m)
    sk['conclusion'] = _entry(conclusion)
    # Distribute visual refs trivially: first n figures/eqs in intro
    for fid, meta in list(content.get('figures', {}).items())[:5]:
        sk['intro']['figures'][fid] = meta.get('caption','')
    for eid, meta in list(content.get('equations', {}).items())[:5]:
        sk['intro']['equations'][eid] = meta.get('text','')[:200]
    sk['_meta'] = {
        'paper_id': content.get('paper_id'),
        'generated_at': dt.datetime.utcnow().isoformat() + 'Z',
        'version': 'skeleton-simple-v1'
    }
    return sk

def save_summary_skeleton(content: Dict[str, Any], out_path: Path) -> Path:
    skeleton = build_summary_skeleton(content)
    out_path.write_text(json.dumps(skeleton, ensure_ascii=False, indent=2), encoding='utf-8')
    return out_path

if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf', required=True)
    ap.add_argument('--tei', required=True)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    pdf_p = Path(args.pdf)
    tei_text = Path(args.tei).read_text(encoding='utf-8')
    out_dir = Path(args.out) if args.out else None
    path = save_content_json(pdf_p, tei_text, out_dir)
    print(f'Wrote {path}')
