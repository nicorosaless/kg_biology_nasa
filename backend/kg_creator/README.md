# kg_creator (Pipeline por fases, salidas segregadas)

Pipeline por documento (single-paper) con salidas intermedias **separadas por subcarpeta** dentro de `processed_grobid_pdfs/<PMCID>/graph/phaseX/` para maximizar trazabilidad y evitar sobreescrituras ambiguas.

## Fases
| Fase | Script | Subcarpeta | Archivo | Descripción |
|------|--------|-----------|---------|-------------|
| 1 | `phase1_parse.py` | `phase1/` | `sections.json` | Filtra y normaliza secciones del `.grobid.content.json` |
| 2 | `phase2_sentences.py` | `phase2/` | `sentences.jsonl` | Segmentación en oraciones vía spaCy (`en_core_web_sm`) con offsets globales |
| 3 | `phase3_entities.py` | `phase3/` | `entities.jsonl` | NER sólo modelos (proveedores: HuggingFace biomédico + spaCy fallback, sin heurísticos) |
| 4 | `phase4_relations.py` | `phase4/` | `relations.jsonl` | Co-ocurrencia oracional + verb patterns | 
| 5 | `phase5_graph.py` | `phase5/` | `graph.json` | Agrega entidades + relaciones + stats |

## Orquestador
Ejemplo (todas las fases):
```bash
python -m kg_creator.run --base processed_grobid_pdfs --pmcid PMC11988870 --phases all
```

Fases específicas (ej: rehacer sólo entidades y relaciones):
```bash
python -m kg_creator.run --base processed_grobid_pdfs --pmcid PMC11988870 --phases 3,4,5
```

## Estructura de salida
```
processed_grobid_pdfs/PMC11988870/
  PMC11988870.grobid.content.json
  graph/
    phase1/
      sections.json
    phase2/
      sentences.jsonl
    phase3/
      entities.jsonl
    phase4/
      relations.jsonl
    phase5/
      graph.json
```

## Formatos
### phase2/sentences.jsonl (ejemplo)
```json
{"sid":12,"section_index":1,"section_heading":"INTRODUCTION","text":"Example sentence.","char_start_section":200,"char_end_section":220,"char_start_global":2378,"char_end_global":2398}
```

### phase3/entities.jsonl (nuevo formato enriquecido)
Cada línea: una entidad con offsets relativos a oración, sección y documento + proveedor que la generó.
```json
{
  "eid": 42,
  "sentence_id": 120,
  "section_index": 3,
  "section_heading": "RESULTS",
  "type": "DISEASE",
  "mention": "thyroid carcinoma",
  "provider": "hf:d4data/biomedical-ner-all",
  "char_start_sentence": 15,
  "char_end_sentence": 33,
  "char_start_section": 1085,
  "char_end_section": 1103,
  "char_start_global": 8123,
  "char_end_global": 8141
}
```

### phase4/relations.jsonl (sin cambios mayores todavía)
```json
{
  "rid": 7,
  "type": "ACTIVATES",
  "source_eid": 42,
  "target_eid": 55,
  "sentence_id": 120,
  "section_heading": "RESULTS",
  "evidence": "Full sentence text here"
}
```

### phase5/graph.json (resumen agregado)
```json
{
  "entity_types": {"DISEASE": 18, "GENE": 12, "CHEMICAL": 9, "PROCESS": 25, "...": 44},
  "relation_types": {"ACTIVATES": 236, "INHIBITS": 26, "REGULATES": 32, "INTERACTS_WITH": 6},
  "n_entities": 1268,
  "n_relations": 300
}
```

## Limitaciones (estado actual tras refactor)
- Segmentación ya basada en spaCy; posible mejora con modelo biomédico específico para oraciones científicas.
- NER biomédico HuggingFace produce etiquetas finas pero aún sin normalización a IDs (UMLS, Entrez, ChEBI...).
- Relación: patrón verbal muy simple + co-ocurrencia; requiere análisis sintáctico y filtrado semántico.
- No hay desambiguación / clustering de menciones (coreference / canonical forms) todavía.
- Sin ranking de confianza multi-modelo (se prioriza proveedor según orden, no score combinado).
- No se hace pruning de spans muy cortos potencialmente ruidosos más allá de longitud mínima.

## Próximos pasos sugeridos
1. Normalización a ontologías (UMLS / MeSH / Gene / Taxonomy) con servicios o diccionarios locales.
2. Incorporar análisis de dependencias para relaciones dirigidas y filtrado de verbos falsos positivos.
3. Scoring compuesto (frecuencia, sección, tipo de verbo, distancia) + pruning de relaciones redundantes.
4. Coreference + canonical mention mapping (unificar variantes de la misma entidad).
5. Exportadores: Neo4j CSV / Cypher, RDF (TTL) y JSON-LD.
6. Batch multi-paper + incremental update (no recalcular fases previas si artefactos sin cambio hash).

---
Refactor completado: offsets globales + sentence, NER exclusivamente por modelos (HF + spaCy fallback), sin heurísticos regex; estructura auditable y extensible.

---
Este rework crea una base transparente y auditable; ahora cada fase es reproducible y aislada.
