# Knowledge Graph Pipeline para Biosciencia Espacial NASA
> Pipeline completo: PDF → Entidades + Relaciones → Grafo Multi-Escala → Insights Accionables

---

## ⚠️ Estado del Proyecto

### ✅ Implementado (Prototipo Funcional)
**Módulo**: `kg_creator/` (código mínimo viable)

**Funcionalidad**:
- ✅ Carga `.content.json` de un paper individual
- ✅ Extrae entidades con heurísticas regex:
  - `ORGANISM`: binomiales latinos (ej: *Homo sapiens*)
  - `SECTION_CONCEPT`: términos clave (gene, protein, microgravity, etc.)
  - `CHEMICAL`: tokens uppercase (IL, NF, ATP, RNA, etc.)
- ✅ Genera relaciones `COOCCURS_WITH` por co-ocurrencia
- ✅ Ingest directo a Neo4j vía Bolt driver

**Uso**:
```bash
python -m kg_creator.run_kg PMC11988870 --wipe  # Procesa 1 paper → Neo4j
```

**Resultado**: Paper ejemplo (PMC11988870) → **164 entidades** + **6,244 relaciones**

**Exports para UI (contrato mínimo)**:
- `graph_core.json` (contract): nodos y edges con sólo campos esenciales + objeto de navegación.
- `graph_vis.json`: versión derivada con layout ligero (color/posición/tamaño) generada automáticamente a partir de `graph_core.json`.
- `section_overview.json`: snapshot de secciones (nodos = secciones, edges opcionales futuro).
- `section_XX_<slug>.json`: subgrafos locales por sección (≤50 nodos) con el mismo esquema mínimo que `graph_core.json`.

### Esquema Mínimo (graph_core.json / section_*.json)
```json
{
  "paper_id": "PMC11988870",
  "nodes": [
    {
      "id": 12,
      "label": "TP53",
      "type": "GENE_PRODUCT",
      "freq": 3,
      "nav": {
        "section": "RESULTS",
        "sentence_id": 145,
        "char_start": 12345,
        "char_end": 12349,
        "anchor": "PMC11988870_12345_12349"
      }
    },
    {
      "id": 47,
      "label": "apoptosis",
      "type": "PROCESS",
      "freq": 5,
      "nav": {"section": "RESULTS", "sentence_id": 146, "char_start": 12510, "char_end": 12519, "anchor": "PMC11988870_12510_12519"}
    }
  ],
  "edges": [
    {"id": 301, "source": 12, "target": 47, "type": "COOCCURS_SENT"}
  ],
  "stats": {"n_entities": 164, "n_relations": 6244}
}
```
Campos eliminados deliberadamente: `created_at`, `color`, `size`, `x`, `y`, evidencia cruda y metadatos secundarios. La UI puede recalcular layout y estilos sin afectar persistencia.

Regeneración: `graph_vis.json` y subgrafos se pueden volver a crear ejecutando nuevamente Fase 5 sin repetir Fases 1–4 siempre que `graph_core.json` exista.

### Navegación (anchor)
El campo `nav.anchor` permite mapear un nodo a una región del PDF/HTML combinando `paper_id` y offsets globales: `<PMCID>_<char_start>_<char_end>`. Puede usarse como id en el visor para hacer scroll directo.

### graph_vis.json (derivado)
Incluye además de `nodes` / `edges`:
```json
{
  "nodes": [
    {"id": 12, "label": "TP53", "type": "GENE_PRODUCT", "color": "#1f77b4", "degree": 14, "frequency": 3, "size": 22.4, "x": 0.6159, "y": -0.7888}
  ],
  "edges": [ {"id": 301, "source": 12, "target": 47, "type": "COOCCURS_SENT"} ],
  "meta": {"paper_id": "PMC11988870", "visual_counts": {"entities": 40, "relations": 88}}
}
```
Se genera automáticamente; si se borra puede regenerarse desde `graph_core.json`.

**Retención mínima recomendada (modo slim)**:
Si quieres ahorrar espacio por paper y sólo necesitas mostrar el grafo:
1. Conservar `summary_and_content/<paper_id>.content.json` (para volver a enriquecer si hiciera falta).
2. Conservar `graph/phase5/graph_core.json` y `graph/phase5/graph_vis.json`.
3. (Opcional) Eliminar o comprimir `phase1`–`phase4` y `graph.json` completo.

Con `graph_core.json` puedes recalcular un nuevo `graph_vis.json` ajustando parámetros (thresholds, layout) sin rehacer NER ni relaciones.

**Subgrafos por sección (actualizado)**:
- Ranking híbrido: `degree` → `frequency` (configurable) para seleccionar hasta `SECTION_SUBGRAPH.max_nodes` (por defecto 50, se puede bajar a 40 si la UI lo requiere).
- Misma estructura mínima que `graph_core.json`:
```json
{
  "paper_id": "PMCXXXX",
  "section": "RESULTS",
  "n_nodes": 37,
  "n_edges": 54,
  "nodes": [ {"id": 12, "label": "TP53", "type": "GENE_PRODUCT", "freq": 3, "nav": {"section": "RESULTS", "sentence_id": 145, "char_start": 12345, "char_end": 12349, "anchor": "PMCXXXX_12345_12349"}} ],
  "edges": [ {"id": 210, "type": "COOCCURS_SENT", "source": 12, "target": 45} ]
}
```

**Limitaciones**:
- ❌ No normaliza entidades a ontologías (UMLS/NCBI/GO)
- ❌ Relaciones basadas en co-ocurrencia global (no contexto oracional)
- ❌ Sin NER científico (SciSpaCy/BioBERT)

---

### 🔮 Roadmap Futuro (Arquitectura `kg_pipeline/`)
El resto de este documento describe la **arquitectura objetivo** en 5 fases con:
- NER científico + normalización UMLS/NCBI
- Extracción de relaciones causales (patterns + LLM)
- Grafo global multi-paper con merge inteligente
- Dashboard interactivo

**Ver carpeta `kg_creator/` para la implementación actual minimal.**

---

## Objetivo del Proyecto
Construir un sistema automatizado de extracción y análisis de Knowledge Graphs (KG) sobre **608 publicaciones biomédicas de NASA** para:
- **Científicos**: Descubrir hipótesis no obvias (e.g., "genes regulados por microgravedad con impacto en reparación ósea").
- **Gerentes de Misión**: Priorizar experimentos críticos (e.g., gaps en proteínas de estrés oxidativo).
- **Dashboard Web**: Visualización interactiva de trends, relaciones causales y líneas de investigación emergentes.

**Dominio**: Efectos de microgravedad/radiación espacial en organismos modelo (ratones, plantas, células), genes, vías metabólicas y procesos biológicos.

**Meta**: Grafo global auditado (50k-200k nodos) con evidencia textual por edge; prototipo funcional en 2 semanas para NASA Challenge.

---
## Arquitectura del Pipeline (5 Fases)

### Fase 1: Adquisición y Parsing Base
**Input**: 608 PMCIDs (CSV)  
**Output**: `processed_grobid_pdfs/<PMCID>/<PMCID>.grobid.content.json`

**Herramientas**:
- `SB_publications/download_pdfs.py`: Descarga batch via APIs (PMC/Europe PMC) con manejo de POW.
- GROBID (Docker `lfoppiano/grobid:0.8.0`): Extracción estructurada (TEI → JSON).
- `summary/process_grobid_pdfs.py`: Orquestador batch con fallback HTTP.

**Formato JSON**:
```json
{
  "metadata": {"title": "...", "authors": [...], "pmcid": "PMC123"},
  "abstract": "...",
  "sections": [
    {"heading": "Results", "text": "...", "paragraphs": [...]},
    ...
  ],
  "figures": [...],
  "references": [...]
}
```

**Criterios de Calidad**:
- Mínimo 500 palabras en secciones Results/Discussion/Conclusions.
- Metadata completa (título, PMCID, año).
- Log de fallos: `failed_pdfs.json` con error codes.

---
### Fase 2: Pre-Procesamiento y Segmentación
**Objetivo**: Texto limpio por oración para NER/LLM.

**Módulos** (nuevo paquete `kg_pipeline/preprocessing/`):
1. **Filtro de Secciones** (`filter_sections.py`):
   - Prioridad: Abstract > Results > Discussion > Conclusions.
   - Descartar: Acknowledgements, References, Supplementary.
   - Output: ~400-800 oraciones por paper.

2. **Limpieza** (`clean_text.py`):
   - Remover citations inline `[1,2]`, tablas mal parseadas, fórmulas LaTeX residuales.
   - Normalización Unicode (e.g., ligaduras "ﬁ" → "fi").
   - Expansión de abreviaciones comunes (e.g., "e.g." → "for example").

3. **Segmentación Oracional** (`sentence_splitter.py`):
   - spaCy `en_core_sci_md` (especializado en bio).
   - Preserva contexto: `{"sent_id": "PMC123_sect2_sent5", "text": "...", "section": "Results"}`.
   - Ventana de 3 oraciones para co-ocurrencia contextual.

**Output**: `processed_sentences/<PMCID>.sentences.json`

---
### Fase 3: Extracción de Entidades (NER + Normalización)
**Objetivo**: Identificar + normalizar entidades biomédicas.

**Stack**:
- **NER Base**: SciSpaCy `en_ner_bc5cdr_md` (Chemical/Disease) + `en_ner_bionlp13cg_md` (Gene/Protein).
- **Normalización**:
  - UMLS Linker (CUI): Conceptos generales (Process, Phenomenon).
  - NCBI Gene: Genes/Proteínas → Entrez ID.
  - NCBI Taxonomy: Organismos → TaxID.
  - ChEBI: Compuestos químicos → ChEBI ID.

**Tipos de Entidades** (ontología cerrada):
```python
ENTITY_TYPES = {
    'ORGANISM': {'source': 'NCBI_Taxonomy', 'id_prefix': 'taxid:'},
    'GENE': {'source': 'NCBI_Gene', 'id_prefix': 'gene:'},
    'PROTEIN': {'source': 'UniProt', 'id_prefix': 'uniprot:'},
    'CHEMICAL': {'source': 'ChEBI', 'id_prefix': 'chebi:'},
    'DISEASE': {'source': 'UMLS', 'id_prefix': 'cui:'},
    'PROCESS': {'source': 'GO', 'id_prefix': 'go:'},  # Biological Process
    'PATHWAY': {'source': 'KEGG', 'id_prefix': 'kegg:'},
    'PHENOMENON': {'custom': True, 'examples': ['microgravity', 'spaceflight', 'radiation']}
}
```

**Módulo** (`kg_pipeline/ner/entity_extractor.py`):
- Input: Oraciones segmentadas.
- Output: `entities/<PMCID>.entities.jsonl` (línea por entidad):
  ```json
  {"ent_id": "E123", "text": "NF-κB", "type": "GENE", "norm_id": "gene:4790", "sent_id": "PMC123_sect2_sent5", "offset": [34, 39], "score": 0.95}
  ```

**Validación**:
- Desambiguación manual para términos ambiguos (e.g., "ROS" → Reactive Oxygen Species vs Robot Operating System).
- Diccionario de stop-entities (e.g., "Figure 1", "Table S1").

---
### Fase 4: Extracción de Relaciones (Reglas + LLM Híbrido)
**Objetivo**: Rels causales/funcionales con evidencia.

**Estrategia Multi-Nivel**:

1. **Co-Ocurrencia Filtrada** (baseline):
   - Ventana: 3 oraciones (contexto local).
   - Tipo: `COOCCURS_WITH` (peso por frecuencia).
   - Solo si tipos distintos (e.g., GENE-PROCESS, no GENE-GENE).

2. **Patrones Lingüísticos** (`kg_pipeline/relations/pattern_matcher.py`):
   - Dependency parsing (spaCy).
   - Patrones:
     ```python
     RELATION_PATTERNS = {
         'INHIBITS': ['inhibit', 'suppress', 'downregulate', 'block'],
         'ACTIVATES': ['activate', 'stimulate', 'upregulate', 'induce'],
         'REGULATES': ['regulate', 'modulate', 'control', 'affect'],
         'INTERACTS_WITH': ['interact', 'bind', 'associate', 'complex'],
         'EXPRESSED_IN': ['express', 'detected in', 'present in']
     }
     ```
   - Validación: Sujeto y objeto deben ser entidades normalizadas.

3. **LLM-Based RE** (opcional, para oraciones complejas):
   - Modelo: BioGPT-Large / PubMedBERT fine-tuned en ChemProt/DDI corpus.
   - Prompt:
     ```
     Extract causal relations from: "{sentence}"
     Entities: {entities_in_sentence}
     Format: [Source Entity] --[RELATION_TYPE]--> [Target Entity]
     ```
   - Threshold: confianza > 0.8 para incluir.

**Módulo** (`kg_pipeline/relations/relation_extractor.py`):
- Input: Entidades + oraciones.
- Output: `relations/<PMCID>.relations.jsonl`:
  ```json
  {"rel_id": "R456", "type": "INHIBITS", "source": "E123", "target": "E789", "evidence": {"sent_id": "...", "text": "NF-κB inhibits apoptosis...", "method": "pattern", "score": 0.92}}
  ```

---
### Fase 5: Construcción y Fusión del Grafo
**Objetivo**: DiGraph por paper + merge global.

**Módulo** (`kg_pipeline/graph/builder.py`):

#### 5.1 Grafo Per-Paper
```python
import networkx as nx

G = nx.DiGraph()
# Nodos
for ent in entities:
    G.add_node(ent['ent_id'], 
               text=ent['text'],
               type=ent['type'],
               norm_id=ent['norm_id'],
               pmcid=pmcid,
               freq=ent_freq[ent['norm_id']])

# Edges
for rel in relations:
    G.add_edge(rel['source'], rel['target'],
               type=rel['type'],
               evidence=rel['evidence']['text'],
               sent_id=rel['evidence']['sent_id'],
               score=rel['evidence']['score'],
               method=rel['evidence']['method'])
```

**Métricas por Paper**:
- Nodos: 150-300 (entidades únicas normalizadas).
- Edges: 200-500 (relaciones con score > threshold).
- Densidad: ~0.01-0.03 (grafos dispersos).
- Top nodos por grado: genes hub (e.g., TP53, MYC).

**Output**: `graphs/per_paper/<PMCID>.gpickle`

#### 5.2 Grafo Global (Merge)
```python
G_global = nx.DiGraph()

for pmcid_graph in all_graphs:
    for node, attrs in pmcid_graph.nodes(data=True):
        norm_id = attrs['norm_id']
        if norm_id not in G_global:
            G_global.add_node(norm_id, **attrs, papers=[pmcid])
        else:
            G_global.nodes[norm_id]['papers'].append(pmcid)
            G_global.nodes[norm_id]['freq'] += attrs['freq']
    
    for u, v, attrs in pmcid_graph.edges(data=True):
        norm_u, norm_v = get_norm_id(u), get_norm_id(v)
        edge_key = (norm_u, norm_v, attrs['type'])
        if G_global.has_edge(norm_u, norm_v):
            G_global[norm_u][norm_v]['weight'] += attrs['score']
            G_global[norm_u][norm_v]['evidences'].append(attrs)
        else:
            G_global.add_edge(norm_u, norm_v, 
                              type=attrs['type'],
                              weight=attrs['score'],
                              evidences=[attrs])
```

**Filtros Post-Merge**:
- Nodos: Mínimo 2 papers de soporte.
- Edges: Weight > 1.5 (agregado multi-paper).
- Top 10% por PageRank para visualización inicial.

**Output**: `graphs/global/global_graph.gpickle` + `global_graph_stats.json`

---
### Fase 6: Persistencia y Export
**Módulos** (`kg_pipeline/export/`):

1. **Neo4j Ingest** (`neo4j_loader.py`):
   ```cypher
   CREATE INDEX norm_id_idx FOR (n:Entity) ON (n.norm_id);
   
   MERGE (e:Entity {norm_id: $norm_id})
   SET e.text = $text, e.type = $type, e.papers = $papers;
   
   MATCH (s:Entity {norm_id: $source}), (t:Entity {norm_id: $target})
   MERGE (s)-[r:RELATION {type: $rel_type}]->(t)
   SET r.weight = $weight, r.evidences = $evidences;
   ```

2. **GraphML Export** (para Gephi/Cytoscape):
   ```python
   nx.write_graphml(G_global, 'graphs/export/global.graphml')
   ```

3. **Summary JSON** (para dashboard):
   ```json
   {
     "total_nodes": 52134,
     "total_edges": 184392,
     "top_hub_genes": ["TP53", "MYC", "NFKB1"],
     "top_pathways": ["Apoptosis", "Cell Cycle", "DNA Repair"],
     "key_findings": [
       "Microgravity inhibits osteoblast differentiation via Wnt pathway (15 papers)",
       "Radiation activates p53-mediated apoptosis in lymphocytes (23 papers)"
     ]
   }
   ```

---
## Estructura de Carpetas (Reemplazo de `kg_creator`)

```
kg_pipeline/
├── __init__.py
├── preprocessing/
│   ├── __init__.py
│   ├── filter_sections.py       # Priorización de secciones
│   ├── clean_text.py             # Limpieza + normalización
│   └── sentence_splitter.py      # Segmentación oracional
├── ner/
│   ├── __init__.py
│   ├── entity_extractor.py       # NER + normalización
│   ├── umls_linker.py            # Wrapper UMLS
│   └── entity_types.py           # Ontología cerrada
├── relations/
│   ├── __init__.py
│   ├── pattern_matcher.py        # Reglas lingüísticas
│   ├── llm_extractor.py          # BioGPT RE (opcional)
│   └── relation_types.py         # Taxonomía relaciones
├── graph/
│   ├── __init__.py
│   ├── builder.py                # Construcción DiGraph per-paper
│   ├── merger.py                 # Fusión global
│   └── metrics.py                # Stats (grado, centralidad)
├── export/
│   ├── __init__.py
│   ├── neo4j_loader.py           # Ingest con driver
│   ├── graphml_export.py         # Export para viz externa
│   └── summary_generator.py      # JSON resumido
├── cli/
│   ├── __init__.py
│   └── run_pipeline.py           # Orquestador CLI
└── config/
    ├── pipeline_config.yaml      # Parámetros globales
    └── entity_mappings.json      # Diccionarios personalizados
```

---
## Ejecución (CLI Unificado)

```bash
# Pipeline completo (por fases)
python -m kg_pipeline.cli.run_pipeline \
  --phase all \
  --input processed_grobid_pdfs \
  --output kg_outputs \
  --config kg_pipeline/config/pipeline_config.yaml

# Solo NER + Relations
python -m kg_pipeline.cli.run_pipeline \
  --phase ner,relations \
  --input processed_sentences \
  --output entities_relations

# Build global graph + ingest Neo4j
python -m kg_pipeline.cli.run_pipeline \
  --phase graph,export \
  --neo4j-uri bolt://localhost:7687 \
  --wipe-neo4j
```

**Config Example** (`pipeline_config.yaml`):
```yaml
preprocessing:
  priority_sections: [abstract, results, discussion, conclusions]
  min_sentence_words: 5
  max_sentences_per_paper: 800

ner:
  scispacy_model: en_ner_bc5cdr_md
  umls_threshold: 0.85
  enable_disambiguation: true

relations:
  methods: [pattern, cooccur]  # llm requires API key
  pattern_threshold: 0.8
  cooccur_window: 3

graph:
  per_paper_min_nodes: 50
  global_min_papers: 2
  edge_weight_threshold: 1.5
```

---
## Métricas de Validación

### Calidad de Datos (por fase)
1. **Parsing**: % PDFs con >500 palabras en secciones clave.
2. **NER**: Precision/Recall en subset anotado (gold standard: 50 papers).
3. **Relations**: Acuerdo inter-anotador (Cohen's κ > 0.7).
4. **Graph**: Densidad, componentes conectados, top-k hub consistency.

### KPIs Finales
- **Cobertura**: >90% de papers con grafo per-paper construido.
- **Consensus**: ≥60% de edges en grafo global soportados por ≥3 papers.
- **Insights**: ≥20 hipótesis no triviales validables (e.g., genes/vías nuevas).

---
## Próximos Pasos (Roadmap 2 Semanas)

### Sprint 1 (Días 1-7)
- [x] GROBID batch completo (608 PDFs).
- [ ] Pre-procesamiento + segmentación oracional.
- [ ] NER en subset (50 papers) + validación.
- [ ] Baseline co-ocurrencia + pattern matching.

### Sprint 2 (Días 8-14)
- [ ] NER completo + normalización UMLS/NCBI.
- [ ] LLM RE opcional (si API disponible).
- [ ] Construcción grafos per-paper + merge global.
- [ ] Ingest Neo4j + dashboard prototipo (Streamlit).

### Mejoras Futuras
- **Active Learning**: Anotación asistida para mejorar NER/RE.
- **Ontology Alignment**: Mapeo a GO/KEGG/Reactome.
- **Temporal Graphs**: Análisis de trends por año.
- **LLM-RAG**: QA sobre el grafo (e.g., "genes más afectados por radiación").

---
## Recursos Clave

**Datos**:
- 608 PMCIDs: `SB_publications/SB_publication_PMC.csv`
- GROBID JSONs: `processed_grobid_pdfs/`

**Infraestructura**:
- GROBID: Docker `lfoppiano/grobid:0.8.0`
- Neo4j: `bolt://localhost:7687` (credentials en `.env`)
- Python: `3.10+` con `spacy`, `scispacy`, `networkx`, `neo4j`

**Referencias**:
- SciSpaCy: https://allenai.github.io/scispacy/
- UMLS: https://www.nlm.nih.gov/research/umls/
- BioGPT: https://github.com/microsoft/BioGPT

---
## Notas de Implementación

**Estado Actual**: 
- ✅ Fase 1 (parsing) funcional.
- ⚠️ Fases 2-6: Esqueleto listo, requiere implementación.
- ❌ `kg_creator/` obsoleto (heurísticas básicas, no normalización).

**Decisiones de Diseño**:
- **Modular**: Cada fase independiente para iteración rápida.
- **Auditable**: Evidencia textual + offsets en cada edge.
- **Escalable**: Procesa 1 paper/seg (≈10min batch completo).
- **Reproducible**: Config YAML + seeds fijos + logs estructurados.

**Riesgos**:
- Normalización UMLS lenta (solución: cache local).
- LLM RE costoso (fallback: solo patterns).
- Neo4j OOM en grafos grandes (solución: batch ingest + índices).