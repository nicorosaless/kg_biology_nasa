# Backend Progress & Next Steps (apptodo.md)

## 1. Resumen del estado actual
El backend procesa PDFs científicos y genera:
- `summary_and_content/`
  - `<paper_id>.content.json`: Texto estructurado (secciones + navegación + offsets) derivado de GROBID.
  - `summary.json`: Resumen LLM (global + metadatos) con keywords/topics (según modo actual full) y `_meta`.
  - `figures/`: Imágenes extraídas y normalizadas (si no se desactiva en el futuro con `--no-figures`).
- `graph/phase1..phase5/`: Pipeline KG (entidades, relaciones y grafos derivados).
  - `phase5/graph_core.json`: Esquema mínimo (nodes / edges) para UI.
  - `phase5/graph_vis.json`: Versión extendida para visualización (layout / estilos).
  - `phase5/section_overview.json` + `phase5/section_*.json`: Subgrafos por sección (cap de nodos) y metadatos.

Scripts clave:
- `backend/full_pipeline.py`: Orquesta Summary + KG, con caché y métricas de tiempo.
- `backend/summary/runsummary.py` y `paper_summary.py`: Construyen summary_and_content.
- `backend/kg_creator/phase[1-5]_*.py`: Fases del grafo.
- `backend/kg_creator/run.py`: Ejecutor de fases.

Características implementadas:
- Caching de summary y KG (detector de existencia `summary.json` / `graph_core.json`).
- Medición de tiempos por paper (`summary_seconds`, `kg_seconds`, `total_seconds`).
- Reducción de ruido en entidades (filtros numéricos, tokens irrelevantes, housekeeping genes, reagents, condiciones experimentales).
- Nuevos tipos de nodo: `EXPERIMENTAL_CONDITION`, `REAGENT` y roles (`HOUSEKEEPING_GENE`, `THERMAL_PARAMETER`, `LAB_REAGENT`).
- Esquema mínimo para frontend (id, label, type, freq/opcional, role, nav anchor) y subgrafos por sección.
- Documentación de generación de grafos (`graph_generation.md`).
- `.gitignore` ampliado para excluir outputs y cachés pesados (HF, virtualenv, builds GROBID, etc.).

## 2. Estructura de almacenamiento (base: `backend/processed_grobid_pdfs/<paper_id>`)
```
<paper_id>/
  summary_and_content/
    <paper_id>.content.json
    summary.json
    figures/
  graph/
    phase1/... (sections.json)
    phase2/... (sentences.jsonl)
    phase3/... (entities*.jsonl)
    phase4/... (relations.jsonl)
    phase5/
      graph_core.json
      graph_vis.json
      section_overview.json
      section_<slug>.json
      stats.json (si existe)
```
Futuros (planeado):
```
user/
  <user_id>/
    visited_papers.json
    recommendations.json (cache)
```

## 3. Artefactos clave para UI
- Navegación: Cada nodo incluye un anchor `<PMCID>_<char_start>_<char_end>` para saltar a texto.
- `graph_core.json`: Base para el rendering rápido (min fields). 
- `summary.json` `_meta.keywords` (ya existen / se pueden reutilizar para recomendación inicial).
- `section_*.json`: Para cargar incrementalmente secciones grandes.

## 4. Lo que falta (Next Steps)
### 4.1 API (conexión frontend)
Objetivo: Servir datos de cada paper y endpoints auxiliares.
Propuesta (FastAPI):
- `GET /papers`: Lista básica (paper_id, título si disponible, counts).
- `GET /papers/{paper_id}/summary`: Devuelve `summary.json` (o subset reducido para UI).
- `GET /papers/{paper_id}/content`: Devuelve `<paper_id>.content.json` (o streaming / paginado por secciones).
- `GET /papers/{paper_id}/graph/core`: `graph_core.json`.
- `GET /papers/{paper_id}/graph/sections`: lista de secciones (`section_overview.json`).
- `GET /papers/{paper_id}/graph/section/{slug}`: subgrafo específico.
- `POST /user/{user_id}/visit`: registra visita (body: paper_id, timestamp).
- `GET /user/{user_id}/recommendations`: retorna recomendaciones basadas en historial.
- (Opcional) `GET /healthz` y `GET /metrics` (para monitoring).

Infra adicional:
- Index en memoria al arrancar (scan de `processed_grobid_pdfs/`).
- Cache LRU ligera para JSON ya parseado.
- Control de errores (404 cuando falta artefacto).

### 4.2 Sistema de recomendación
Primera versión (heurística simple):
1. Guardar en `backend/processed_grobid_pdfs/user/<user_id>/visited_papers.json`:
   ```json
   {"user_id": "u1", "visits": [{"paper_id": "PMC123", "ts": "2025-10-04T20:00:00Z"}, ...]}
   ```
2. Construir vector de interés del usuario agregando keywords (frecuencia + decay temporal opcional).
3. Para cada paper disponible:
   - Score = suma de coincidencias de keywords normalizada por longitud (TF-IDF opcional más adelante).
4. Retornar top-N (excluir ya visitados recientes).

Evolución posterior:
- Sustituir keywords por embedding promedio (LLM o modelo bio emb). 
- Filtrado colaborativo (cuando haya múltiples usuarios).
- Contexto de sesión (últimas N visitas priorizadas).
- Diversificación (MMR) para no recomendar sólo papers casi idénticos.

### 4.3 Flags de rendimiento pendientes
- `--summary-mode fast` (reduce tokens y pasos).
- `--no-figures`.
- Paralelización de múltiple PDFs (ThreadPool + rate limit LLM).
- Hash semántico para invalidación fina (versión de pipeline + modelo + hash PDF).

### 4.4 Observabilidad
- Guardar `summary_perf_log.ndjson` con tiempos.
- Endpoint `/metrics` (Prometheus) exponiendo conteos y latencias agregadas.

## 5. Riesgos y mitigaciones
| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Crecimiento de directorio `processed_grobid_pdfs/` | Espacio disco | Limpieza programada / TTL |
| Cambios de esquema rompan frontend | Errores UI | Versionar `_meta.schema_version` |
| Latencia LLM | UX lenta | Fast mode + caching |
| Recomendaciones triviales | Poca utilidad | Iterar a embeddings y diversificación |

## 6. Checklist restante (alto nivel)
- [ ] Implementar `api.py` (FastAPI) con endpoints base.
- [ ] Capa de indexado inicial y cache JSON.
- [ ] Persistencia de visitas usuario.
- [ ] Recomendador básico por keywords.
- [ ] Flags de rendimiento (fast mode / no-figures / paralelo).
- [ ] Métricas + health endpoints.
- [ ] Documentar API (OpenAPI auto + README sección). 

## 7. Convenciones propuestas
- Nombres de endpoints en minúscula.
- Respuestas JSON con `status` y `data` cuando aplique.
- Errores: `{ "error": { "code": "not_found", "message": "..." } }`.
- Versionado inicial en ruta opcional (ej. `/v1/...`) si se espera evolución fuerte.

## 8. Próximo paso inmediato sugerido
Crear `backend/api.py` (FastAPI) con: `/healthz`, `/papers`, `/papers/{paper_id}/graph/core`, `/papers/{paper_id}/summary` y estructura para inyectar recomendador luego.

---
Documento generado para alinear estado actual y próximos pasos del backend.

---

## 9. Estado actualizado (2025-10-05)
Las partes base de `api.py` y endpoints de paper/summary/graph/figures ya existen. El foco actual pasa a:

### 9.1 Procesamiento masivo cluster C103 (Radiation & Shielding)
- [ ] Ejecutar full pipeline (summary + KG) para todos los PMC del cluster C103 aún no procesados.
  - Reutilizar caching; usar flags `--overwrite` sólo si falta heurística de figuras nueva.
  - Registrar tiempos agregados y conteo de figuras retenidas (`_meta.figure_selection`).
- [ ] Generar un índice JSON (`backend/output/cluster_C103_status.json`) con: PMCID, title, processed(bool), figures_kept, word_count, graph_nodes, graph_edges.

### 9.2 Mejora UI Summary + Figures
Problema: La vista actual de `PaperDetail.tsx` muestra secciones y figuras pero el layout no mantiene una jerarquía visual clara (figuras a veces descontextualizadas verticalmente y sin zoom dedicado).

Acciones:
- [ ] Reestructurar rendering de summary para iterar TODAS las secciones en orden exacto de `summary.json` (ya se hace) pero:
  - Envolver cada sección en un contenedor CSS consistente (p.ej. grid responsive: texto a la izquierda, figuras apiladas / carrusel a la derecha si >1) o layout vertical armonizado.
  - Añadir ancla HTML por sección: `id="sec-{index}"` y para cada figura `id="fig-{id}"`.
  - Insertar subtítulo automático para figura: `Figure X:` usando label si existe; fallback orden.
- [ ] Implementar modal (portal) al click sobre la miniatura con zoom, caption completa, botón "Open original".
- [ ] Navegación interna: Al pasar el mouse sobre referencia futura (si se añaden referencias de texto a figura) resaltar miniatura.
- [ ] Asegurar scroll suave a figura desde URL hash `#fig-<id>`.

### 9.3 Acciones técnicas backend relacionadas
- [ ] Endpoint opcional `/api/paper/{pmcid}/figure-selection` devolviendo `_meta.figure_selection` para debug UI (no crítico).
- [ ] Validación al servir summary: si `_meta.figure_selection.kept` < 1 reintentar heurística (modo fallback) opcional.

### 9.4 Métricas / logging (post UI fix)
- [ ] Guardar `figure_selection_log.ndjson` con pmcid, kept_ids, discarded_count, timestamp.

### 9.5 Riesgos inmediatos
| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Layout inconsistente en distintos tamaños de pantalla | Mala UX | Usar contenedor responsive + pruebas breakpoints |
| Demasiados fetch simultáneos al cargar muchos papers | Latencia / CORS | Batch y cache local (indexed map) |
| Captions muy largas rompen layout | Scroll vertical excesivo | Truncar con “ver más” en modal |

### 9.6 Checklist sintético actual
- [ ] Pipeline masivo cluster C103
- [ ] Índice de estado cluster
- [ ] Rediseño layout summary/figures
- [ ] Modal zoom figuras
- [ ] Anchors y navegación figuras
- [ ] Endpoint figure-selection (debug)
- [ ] Logging selección figuras

---
Actualización añadida automáticamente.
