from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Set
import json
from collections import defaultdict, Counter, deque
import csv

from .utils import get_phase_dir, save_json
from . import config as KG_CONFIG
from math import sin, cos, pi

# Simplification configuration
PUBLISH_PUBLICATION_NODE = True
PUBLICATION_TYPE = 'PUBLICATION'
EVIDENCE_REL_TYPE = 'PUBLICATION_EVIDENCES_ENTITY'

EXPLANATORY_FIELDS = {
    'eid',        # unique id
    'mention',    # surface form
    'node_type',  # semantic type
    'role',       # semantic role (housekeeping, reagent, etc.)
}


def load_entities(base_dir: Path, pmcid: str) -> List[Dict[str, Any]]:
    p3 = get_phase_dir(base_dir, pmcid, 3)
    path = p3 / 'entities.jsonl'
    if not path.exists():
        raise FileNotFoundError('Run phase3 before phase5 (missing entities.jsonl)')
    ents = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            ents.append(json.loads(line))
    return ents


def load_relations(base_dir: Path, pmcid: str) -> List[Dict[str, Any]]:
    p4 = get_phase_dir(base_dir, pmcid, 4)
    path = p4 / 'relations.jsonl'
    if not path.exists():
        raise FileNotFoundError('Run phase4 before phase5 (missing relations.jsonl)')
    rels = []
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            rels.append(json.loads(line))
    return rels


def _is_noisy_mention(mention: str) -> bool:
    """Heuristic noise filter to drop low-value nodes for UI minimal graph.
    Filters numeric-only, figure/table references, very short tokens (len<3) except gene-like symbols.
    """
    import re
    if not mention:
        return True
    m = mention.strip()
    if not m:
        return True
    # pure digits or digits+letter (e.g. 12, 12A)
    if re.fullmatch(r"\d+[A-Za-z]?", m):
        return True
    # Figure/Table references
    if re.match(r"^(fig(ure)?|table|supp(lement)?)(\b|[ _-]?\d)", m, flags=re.IGNORECASE):
        return True
    # Short tokens (<=2) often noise unless they contain a digit or are all caps gene-like handled earlier
    if len(m) <= 2:
        return True
    # Mostly punctuation
    if all(not c.isalnum() for c in m):
        return True
    return False


def _simplify_entities(raw_entities: List[Dict[str, Any]], pmcid: str) -> List[Dict[str, Any]]:
    """Collapse raw entity occurrences into unique entity records with frequency, sections and navigation anchor.
    Navigation anchor points to first occurrence offsets for PDF linking.
    """
    eid_sections: Dict[str, Set[str]] = defaultdict(set)
    eid_sentence_counts: Counter = Counter()
    first_occ: Dict[str, Dict[str, Any]] = {}

    for e in raw_entities:
        eid = e['eid']
        if 'section_heading' in e and e['section_heading']:
            eid_sections[eid].add(e['section_heading'])
        if 'sentence_id' in e:
            eid_sentence_counts[eid] += 1
        if eid not in first_occ:
            first_occ[eid] = e

    simplified: List[Dict[str, Any]] = []
    for eid, first in first_occ.items():
        mention = first.get('mention') or first.get('canonical') or str(eid)
        if _is_noisy_mention(mention):
            continue
        base = {
            'eid': eid,
            'mention': mention,
            'node_type': first.get('node_type'),
            'role': first.get('role')
        }
        base['frequency'] = eid_sentence_counts.get(eid, 1)
        # Keep full sections internally (used for section subgraphs + visualization)
        base['sections'] = sorted(list(eid_sections.get(eid, [])))
        # Navigation object (first occurrence)
        c_start = first.get('char_start_global')
        c_end = first.get('char_end_global')
        nav = {
            'section': first.get('section_heading'),
            'sentence_id': first.get('sentence_id'),
            'char_start': c_start,
            'char_end': c_end,
            'anchor': f"{pmcid}_{c_start}_{c_end}" if c_start is not None and c_end is not None else None
        }
        base['nav'] = nav
        simplified.append(base)
    return simplified


def _add_publication_node(entities: List[Dict[str, Any]], pmcid: str) -> Dict[str, Any]:
    pub_node = {
        'eid': f'PUB_{pmcid}',
        'mention': pmcid,
        'node_type': PUBLICATION_TYPE,
        'frequency': 1,
        'sections': []
    }
    entities.append(pub_node)
    return pub_node


def _publication_evidence_edges(pub_node: Dict[str, Any], entities: List[Dict[str, Any]], relations: List[Dict[str, Any]], start_rid: int) -> int:
    rid = start_rid
    # Only attach publication to isolated nodes (no existing degree)
    degree = defaultdict(int)
    for r in relations:
        degree[r['source_eid']] += 1
        degree[r['target_eid']] += 1
    for e in entities:
        if e['eid'] == pub_node['eid']:
            continue
        if degree.get(e['eid'], 0) > 0:
            continue
        relations.append({
            'rid': rid,
            'type': EVIDENCE_REL_TYPE,
            'source_eid': pub_node['eid'],
            'target_eid': e['eid'],
            'sentence_id': None,
            'section_heading': None,
            'evidence_span': None,
            'method': 'PUBLICATION_LINK',
            'trigger': None,
            'pattern_type': 'EVIDENCE'
        })
        rid += 1
    return rid


def _compute_connectivity_stats(entities: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> Dict[str, Any]:
    # Build adjacency
    adj: Dict[str, Set[str]] = defaultdict(set)
    for r in relations:
        a = r['source_eid']; b = r['target_eid']
        adj[a].add(b)
        adj[b].add(a)
    all_nodes = {e['eid'] for e in entities}
    visited: Set[str] = set()
    components = []
    for n in all_nodes:
        if n in visited:
            continue
        comp = []
        dq = deque([n])
        visited.add(n)
        while dq:
            cur = dq.popleft()
            comp.append(cur)
            for nb in adj.get(cur, []):
                if nb not in visited:
                    visited.add(nb)
                    dq.append(nb)
        components.append(comp)
    components_sorted = sorted(components, key=len, reverse=True)
    largest = len(components_sorted[0]) if components_sorted else 0
    return {
        'n_components': len(components_sorted),
        'largest_component_size': largest,
        'component_size_distribution': [len(c) for c in components_sorted[:10]]
    }


def _degree_metrics(entities: List[Dict[str, Any]], relations: List[Dict[str, Any]]):
    deg = defaultdict(int)
    for r in relations:
        deg[r['source_eid']] += 1
        deg[r['target_eid']] += 1
    degrees = [deg.get(e['eid'], 0) for e in entities]
    if not degrees:
        return {'avg_degree': 0, 'median_degree': 0, 'isolated_nodes': 0}
    degrees_sorted = sorted(degrees)
    mid = len(degrees)//2
    if len(degrees) % 2:
        median = degrees_sorted[mid]
    else:
        median = (degrees_sorted[mid-1] + degrees_sorted[mid]) / 2
    return {
        'avg_degree': sum(degrees)/len(degrees),
        'median_degree': median,
        'isolated_nodes': sum(1 for d in degrees if d == 0)
    }


def _force_connectivity(pub_node: Dict[str, Any], entities: List[Dict[str, Any]], relations: List[Dict[str, Any]]):
    """If multiple components remain and FORCE_PUBLICATION_CONNECTIVITY, connect all nodes to publication."""
    if not getattr(KG_CONFIG, 'FORCE_PUBLICATION_CONNECTIVITY', False):
        return
    # recompute components
    adj = defaultdict(set)
    for r in relations:
        a = r['source_eid']; b = r['target_eid']
        adj[a].add(b); adj[b].add(a)
    all_nodes = {e['eid'] for e in entities if e['eid'] != pub_node['eid']}
    visited = set()
    components = []
    for n in all_nodes:
        if n in visited: continue
        comp = []
        dq = deque([n]); visited.add(n)
        while dq:
            cur = dq.popleft(); comp.append(cur)
            for nb in adj.get(cur, []):
                if nb not in visited:
                    visited.add(nb); dq.append(nb)
        components.append(comp)
    if len(components) <= 1:
        return
    # connect any node not already adjacent to publication
    current_degree = {r['target_eid'] for r in relations if r['source_eid']==pub_node['eid']} | {r['source_eid'] for r in relations if r['target_eid']==pub_node['eid']}
    max_rid = max([r.get('rid', -1) for r in relations] + [-1]) + 1
    for e in entities:
        if e['eid'] == pub_node['eid']:
            continue
        if e['eid'] in current_degree:
            continue
        relations.append({
            'rid': max_rid,
            'type': EVIDENCE_REL_TYPE,
            'source_eid': pub_node['eid'],
            'target_eid': e['eid'],
            'sentence_id': None,
            'section_heading': None,
            'evidence_span': None,
            'method': 'PUBLICATION_CONNECTIVITY',
            'trigger': None,
            'pattern_type': 'EVIDENCE'
        })
        max_rid += 1


def aggregate(entities: List[Dict[str, Any]], relations: List[Dict[str, Any]], pmcid: str) -> Dict[str, Any]:
    simplified_entities = _simplify_entities(entities, pmcid)
    # Filter relations referencing removed (noisy) entities
    valid_eids = {e['eid'] for e in simplified_entities}
    relations = [r for r in relations if r['source_eid'] in valid_eids and r['target_eid'] in valid_eids]
    if PUBLISH_PUBLICATION_NODE:
        pub_node = _add_publication_node(simplified_entities, pmcid)
        max_rid = max([r.get('rid', -1) for r in relations] + [-1]) + 1
        _publication_evidence_edges(pub_node, simplified_entities, relations, max_rid)
        # enforce connectivity if still fragmented
        _force_connectivity(pub_node, simplified_entities, relations)

    ent_type_counts = Counter(e['node_type'] for e in simplified_entities)
    rel_type_counts = Counter(r['type'] for r in relations)
    connectivity = _compute_connectivity_stats(simplified_entities, relations)
    degree_stats = _degree_metrics(simplified_entities, relations)
    relations_with_trigger = sum(1 for r in relations if r.get('trigger'))
    rel_trigger_pct = (relations_with_trigger / len(relations) * 100) if relations else 0.0

    stats = {
        'entity_types': dict(ent_type_counts),
        'relation_types': dict(rel_type_counts),
        'n_entities': len(simplified_entities),
        'n_relations': len(relations),
        'relations_with_trigger_pct': round(rel_trigger_pct, 2),
        **connectivity,
        **degree_stats
    }
    return {
        'entities': simplified_entities,
        'relations': relations,
        'stats': stats
    }


def run(base_dir: Path, pmcid: str):
    ents = load_entities(base_dir, pmcid)
    rels = load_relations(base_dir, pmcid)
    graph = aggregate(ents, rels, pmcid)
    out_dir = get_phase_dir(base_dir, pmcid, 5)
    save_json(graph, out_dir / 'graph.json')
    save_json(graph['stats'], out_dir / 'stats.json')
    # Core lightweight export (enough to rebuild graph_vis):
    # Keep only: entities[eid, mention, node_type, frequency, sections], relations[rid, source_eid, target_eid, type]
    # Minimal core export (UI contract): nodes & edges only with essential fields + navigation
    core = {
        'paper_id': pmcid,
        'nodes': [
            {
                'id': e['eid'],
                'label': e.get('mention'),
                'type': e.get('node_type'),
                'role': e.get('role'),
                'freq': e.get('frequency'),
                'nav': e.get('nav')  # {section, sentence_id, char_start, char_end, anchor}
            } for e in graph['entities']
        ],
        'edges': [
            {
                'id': r.get('rid'),
                'source': r['source_eid'],
                'target': r['target_eid'],
                'type': r.get('type')
            } for r in graph['relations']
        ],
        'stats': graph['stats']
    }
    save_json(core, out_dir / 'graph_core.json')
    # Visualization export
    try:
        vis = build_visualization_graph(graph, pmcid)
        save_json(vis, out_dir / 'graph_vis.json')
    except Exception as e:  # non-fatal
        save_json({'error': 'vis_generation_failed', 'message': str(e)}, out_dir / 'graph_vis.error.json')
    # Section subgraphs
    try:
        if getattr(KG_CONFIG, 'SECTION_SUBGRAPH', {}).get('enabled', False):
            section_exports = build_section_subgraphs(graph, pmcid)
            save_json(section_exports['overview'], out_dir / 'section_overview.json')
            for sec_file, sec_obj in section_exports['sections'].items():
                save_json(sec_obj, out_dir / sec_file)
    except Exception as e:
        save_json({'error': 'section_subgraphs_failed', 'message': str(e)}, out_dir / 'section_subgraphs.error.json')
    # --- Neo4j export ---
    neo_dir = out_dir / 'neo4j'
    neo_dir.mkdir(exist_ok=True)
    nodes_path = neo_dir / 'nodes.csv'
    rels_path = neo_dir / 'relationships.csv'

    # Nodes CSV schema: id:ID,mention,frequency:int,node_type:LABEL,sections (pipe-delimited)
    with nodes_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['id:ID','mention','frequency:int','node_type:LABEL','sections'])
        for n in graph['entities']:
            sections_join = '|'.join(n.get('sections', []))
            w.writerow([n['eid'], n.get('mention',''), n.get('frequency',0), n.get('node_type','ENTITY'), sections_join])

    # Relationships CSV schema: :START_ID,:END_ID,type:TYPE,method,trigger,evidence_span,section_heading,sentence_id:int
    with rels_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([':START_ID',':END_ID','type:TYPE','method','trigger','evidence_span','section_heading','sentence_id:int'])
        for r in graph['relations']:
            w.writerow([
                r['source_eid'],
                r['target_eid'],
                r.get('type','RELATED_TO'),
                r.get('method',''),
                r.get('trigger','') or '',
                (r.get('evidence_span','') or '').replace('\n',' '),
                r.get('section_heading','') or '',
                r.get('sentence_id') if isinstance(r.get('sentence_id'), int) else ''
            ])
    return graph['stats']

if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--pmcid', required=True)
    a = p.parse_args()
    print(run(Path(a.base), a.pmcid))

# ---------------- Visualization helpers (appended) ----------------

def build_visualization_graph(graph: Dict[str, Any], pmcid: str) -> Dict[str, Any]:
    """Produce a UI-friendly reduced graph with:
      - Node filtering (max nodes)
      - Degree + frequency based scoring
      - Deterministic simple layout (radial or circular)
      - Color & size attributes
    Layout is intentionally lightweight (no heavy libs) so UI can refine later.
    """
    cfg = getattr(KG_CONFIG, 'VISUALIZATION', {})
    max_nodes = cfg.get('max_nodes', 120)
    strict_max = cfg.get('max_nodes_strict', max_nodes)
    min_freq = cfg.get('min_frequency', 1)
    priority_types = cfg.get('priority_types', [])
    palette = cfg.get('colors', {})
    layout_mode = cfg.get('layout', 'radial')
    size_cfg = cfg.get('node_size', {'min':4,'max':28})

    # Support both full graph (phase5) structure and minimal core schema
    if 'entities' in graph and 'relations' in graph:
        entities = graph['entities']
        relations = graph['relations']
        ent_id_key = 'eid'
        rel_src_key = 'source_eid'
        rel_tgt_key = 'target_eid'
    else:
        # assume minimal core-like graph already transformed earlier
        entities = graph.get('nodes', [])
        relations = graph.get('edges', [])
        ent_id_key = 'id'
        rel_src_key = 'source'
        rel_tgt_key = 'target'
    # Build degree map
    degree = {e[ent_id_key]:0 for e in entities}
    for r in relations:
        degree[r[rel_src_key]] = degree.get(r[rel_src_key],0)+1
        degree[r[rel_tgt_key]] = degree.get(r[rel_tgt_key],0)+1

    # Score: (is_priority, degree, frequency)
    scored = []
    for e in entities:
        freq = e.get('frequency', e.get('freq', 1))
        if freq < min_freq:
            continue
        node_type = e.get('node_type') or e.get('type')
        is_prio = 1 if node_type in priority_types else 0
        scored.append((is_prio, degree.get(e[ent_id_key],0), freq, e))
    # Sort descending by priority, degree, freq
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    # Apply caps
    selected_entities = [t[3] for t in scored[:strict_max]]
    selected_ids = {e[ent_id_key] for e in selected_entities}
    # Filter relations to those connecting selected nodes
    filtered_rels = [r for r in relations if r['source_eid'] in selected_ids and r['target_eid'] in selected_ids]
    # If still too many nodes (< max_nodes) we keep; else trim again by degree only
    if len(selected_entities) > max_nodes:
        selected_entities = selected_entities[:max_nodes]
        selected_ids = {e['eid'] for e in selected_entities}
        filtered_rels = [r for r in filtered_rels if r['source_eid'] in selected_ids and r['target_eid'] in selected_ids]

    # Recompute degree within subgraph
    sub_degree = {e[ent_id_key]:0 for e in selected_entities}
    for r in filtered_rels:
        sub_degree[r[rel_src_key]] += 1
        sub_degree[r[rel_tgt_key]] += 1

    # Size scaling
    if selected_entities:
        d_vals = list(sub_degree.values())
        d_min, d_max = min(d_vals), max(d_vals)
    else:
        d_min = d_max = 0
    size_min = size_cfg.get('min',4); size_max = size_cfg.get('max',28)
    def scale_size(d):
        if d_max == d_min:
            return (size_min + size_max)/2
        return size_min + (d - d_min) / (d_max - d_min) * (size_max - size_min)

    # Layout assignment
    n = len(selected_entities)
    positions = {}
    if n == 0:
        positions = {}
    elif layout_mode in ('radial','circular'):
        radius = 1.0
        for idx, e in enumerate(selected_entities):
            angle = 2 * pi * (idx / max(1,n))
            r = radius
            if layout_mode == 'radial' and sub_degree[e[ent_id_key]] > 0 and d_max>0:
                # pull hubs slightly inward
                hub_factor = 0.4 + 0.6 * (1 - sub_degree[e[ent_id_key]] / d_max)
                r = radius * hub_factor
            positions[e[ent_id_key]] = {'x': round(r * cos(angle), 4), 'y': round(r * sin(angle), 4)}
    else:  # random fallback deterministic (seedless simple spread)
        for idx, e in enumerate(selected_entities):
            positions[e['eid']] = {'x': round(((idx*37)%100)/50 - 1,4), 'y': round(((idx*91)%100)/50 - 1,4)}

    vis_nodes = []
    for e in selected_entities:
        node_type = e.get('node_type') or e.get('type') or 'ENTITY'
        vis_nodes.append({
            'id': e.get(ent_id_key),
            'label': e.get('mention') or e.get('canonical') or e.get('label') or str(e.get(ent_id_key)),
            'type': node_type,
            'color': palette.get(node_type, '#cccccc'),
            'degree': sub_degree.get(e.get(ent_id_key),0),
            'sections': e.get('sections', []),
            'frequency': e.get('frequency', e.get('freq',1)),
            'size': round(scale_size(sub_degree.get(e.get(ent_id_key),0)),2),
            **positions.get(e.get(ent_id_key), {'x':0,'y':0})
        })

    vis_edges = []
    for r in filtered_rels:
        vis_edges.append({
            'id': r.get('rid') or r.get('id'),
            'source': r.get('source_eid') if 'source_eid' in r else r.get('source'),
            'target': r.get('target_eid') if 'target_eid' in r else r.get('target'),
            'type': r.get('type','RELATED_TO'),
            'method': r.get('method'),
            'trigger': r.get('trigger')
        })

    meta = {
        'paper_id': pmcid,
        'original_counts': {
            'entities': len(graph['entities']),
            'relations': len(graph['relations'])
        },
        'visual_counts': {
            'entities': len(vis_nodes),
            'relations': len(vis_edges)
        },
        'config_used': {
            'layout': layout_mode,
            'max_nodes': max_nodes,
            'strict_max': strict_max,
            'min_frequency': min_freq
        }
    }
    return {'nodes': vis_nodes, 'edges': vis_edges, 'meta': meta}


def build_section_subgraphs(graph: Dict[str, Any], pmcid: str) -> Dict[str, Any]:
    cfg = getattr(KG_CONFIG, 'SECTION_SUBGRAPH', {})
    max_nodes = cfg.get('max_nodes', 50)
    min_freq = cfg.get('min_frequency', 1)
    ranking = cfg.get('ranking', 'degree_frequency')
    include_cross = cfg.get('include_cross_section_edges', False)
    slug_max = cfg.get('slug_max_len', 40)
    # Map entity id -> entity
    entities = {e['eid']: e for e in graph['entities']}
    # Build degree for ranking
    deg = {eid:0 for eid in entities}
    for r in graph['relations']:
        deg[r['source_eid']] = deg.get(r['source_eid'],0)+1
        deg[r['target_eid']] = deg.get(r['target_eid'],0)+1
    # Collect sections present (from entity sections + relation section_heading)
    section_set = set()
    for e in entities.values():
        for s in e.get('sections', []):
            if s:
                section_set.add(s)
    for r in graph['relations']:
        sec = r.get('section_heading')
        if sec:
            section_set.add(sec)
    sections = sorted(section_set)
    # Index relations per section (primary = relation.section_heading)
    rels_by_section = {s: [] for s in sections}
    for r in graph['relations']:
        sec = r.get('section_heading')
        if sec in rels_by_section:
            rels_by_section[sec].append(r)
    # Build overview edges between sections (if relations link entities whose sections overlap different headings)
    # Simplify: if relation.section_heading == S we just increment internal counts; cross-section edges optional via entity sections.
    overview_nodes = []
    overview_edges = []
    # Precompute simple counts
    sec_internal_rel_count = {s: len(rels_by_section[s]) for s in sections}
    for idx, s in enumerate(sections):
        overview_nodes.append({'id': idx, 'section': s, 'relations': sec_internal_rel_count[s]})
    # Cross section: derive by scanning relations and seeing if source/target share multiple sections; skip for now to keep it simple.
    # Ranking helper
    def rank_entity(eid: int):
        e = entities[eid]
        freq = e.get('frequency',1)
        if ranking == 'frequency':
            return (freq, deg[eid])
        return (deg[eid], freq)
    section_outputs = {}
    def slugify(name: str) -> str:
        import re
        slug = re.sub(r'[^a-zA-Z0-9]+','-', name.strip()).strip('-')
        if len(slug) > slug_max:
            slug = slug[:slug_max]
        return slug or 'section'
    for s in sections:
        rels_sec = rels_by_section.get(s, [])
        # Collect entity ids appearing in this section (via relations + entities listing section)
        eids = set()
        for r in rels_sec:
            eids.add(r['source_eid']); eids.add(r['target_eid'])
        # Add standalone entities that list this section but no relations (optional, keep if space remains)
        standalone = [eid for eid, e in entities.items() if s in (e.get('sections') or []) and eid not in eids]
        # Rank entities
        ranked = sorted(list(eids), key=rank_entity, reverse=True)
        if len(ranked) < max_nodes and standalone:
            extra = sorted(standalone, key=rank_entity, reverse=True)
            ranked.extend(extra)
        # Trim
        ranked = [eid for eid in ranked if entities[eid].get('frequency',1) >= min_freq][:max_nodes]
        ranked_set = set(ranked)
        # Filter relations to those whose both endpoints in ranked_set
        rels_filtered = [r for r in rels_sec if r['source_eid'] in ranked_set and r['target_eid'] in ranked_set]
        # Optionally pull in cross-section edges (disabled by default)
        if include_cross:
            for r in graph['relations']:
                if r in rels_filtered:
                    continue
                if r['source_eid'] in ranked_set and r['target_eid'] in ranked_set:
                    if r.get('section_heading') != s:
                        rels_filtered.append(r)
        # Build output objects
        # Minimal nodes/edges schema (mirror graph_core.json)
        nodes_out = []
        for eid in ranked:
            e = entities[eid]
            nodes_out.append({
                'id': eid,
                'label': e.get('mention'),
                'type': e.get('node_type'),
                'freq': e.get('frequency'),
                'nav': e.get('nav')  # carry navigation anchor for cross-file consistency
            })
        edges_out = [
            {
                'id': r.get('rid'),
                'type': r.get('type'),
                'source': r['source_eid'],
                'target': r['target_eid']
            } for r in rels_filtered
        ]
        section_outputs[f"section_{sections.index(s):02d}_{slugify(s)}.json"] = {
            'paper_id': pmcid,
            'section': s,
            'n_nodes': len(nodes_out),
            'n_edges': len(edges_out),
            'nodes': nodes_out,
            'edges': edges_out
        }
    overview = {
        'paper_id': pmcid,
        'sections': overview_nodes,
        'edges': overview_edges,
        'meta': {
            'total_sections': len(sections)
        }
    }
    return {'overview': overview, 'sections': section_outputs}
