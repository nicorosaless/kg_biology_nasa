## Roadmap KG (Versión Resumida)

### Objetivo
Grafo biomédico con entidades clave (genes, pathways, procesos, fenotipos, cell types, químicos) y relaciones semánticas con evidencia limpia y métricas.

### Estado Actual (Hecho)
- Pipeline fases 1–5 operativo + conectividad garantizada.
- NER híbrido (HF + spaCy) con caché y normalización básica (`canonical`).
- Relaciones por co-ocurrencia tipadas (interacción, expresión, pathway involvement, cell_type ↔ phenotype).
- Export Neo4j (CSV) + script de carga `loadcypher.py`.
- Métricas estructurales (`stats.json`).
- Subgrafos por sección + overview (`section_overview.json`, `section_XX_<slug>.json`) para limitar visualización a ≤50 nodos por vista.

### Gaps Clave
- Fragmentos / sobre-segmentación inflando GENE_PRODUCT.
- Triggers verbales casi inexistentes (<1%).
- Evidencias con saltos de línea y texto sin limpiar.
- Sin reconstrucción de compuestos (micro + gravity).
- No ontologías externas (HGNC / GO / Cell Ontology).
- Edges de publicación añaden ruido visual si se busca vista semántica (posible excluirlos en subgrafos sección).

### Prioridades Inmediatas (Sprint)
1. Limpieza evidencia (`evidence_span`: quitar \n, colapsar espacios, ventana corta).
2. Filtrar fragmentos cortos (len<5 y freq=1 que no son genes) + excluir publication edges en subgrafos.
3. Reconstrucción de compuestos frecuentes (microgravity, cardiomyocyte differentiation, etc.).
4. Verb triggers con lematización y dirección (subir % a >20% inicial, objetivo 40%).
5. Ontología ligera (HGNC symbols + cell types diccionario) para consolidar.
6. Mejora ranking subgrafos sección (añadir PageRank local / centralidad intermedia opcional).

### MVP Criterios
- ≥6 tipos entidad, ninguno >45%.
- ≥5 tipos de relación (sin contar publication) con ≥2 instancias.
- <10% nodos aislados antes de forzar conectividad.
- ≥40% relaciones con trigger.

### Backlog Resumido
- Merge spans fragmentados y eliminar hijos.
- Export adicional `relationships.semantic.csv` sin evidencias de publicación.
- Diccionarios externos (HGNC, GO, Cell Ontology) opcionales.
- Métricas avanzadas: centrality top 1%, ratio canonical/raw.
- Batch multi-PMCID + flags CLI (forzar conectividad / excluir publication / modo sección-only).
- Recalcular subgrafos on-demand a partir de `graph_core.json` sin rehacer NER/relations.
- quality_report.py + tests normalization/merge.

### Decisiones Pendientes
- Crear tipo ENVIRONMENT para microgravity o mantener PHENOTYPE.
- Límite entidades co-ocurrencia (revisar 8).
- Introducir dynamic relationship labels (APOC) vs propiedad `type`.

### Próximo Paso Recomendado
Implementar limpieza de evidencia + filtro fragmentos → regenerar CSV Neo4j + validar que cada sección tiene ≤50 nodos y distribución de tipos balanceada.

---
Documento completo original fue condensado para foco operativo.

