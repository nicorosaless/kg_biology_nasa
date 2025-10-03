# Pipeline Actual (Estado Experimental / No Funcional)

Este documento describe el flujo previsto del sistema desde los PDFs originales hasta la inserción de nodos y relaciones en Neo4j. Refleja **el estado actual**, que es **prototípico** y **no produce todavía un grafo científicamente fiable**.

## Resumen de Etapas
1. Descarga de PDFs (fuente: listado CSV con identificadores PMC)
2. Extracción estructurada con GROBID → TEI XML → conversión a JSON reducido (`*.grobid.content.json`)
3. Construcción de grafo: heurísticas simples de extracción de entidades y co‑ocurrencias
4. Exportación / Ingesta en Neo4j (CSV + Cypher o vía driver Bolt)

---
## 1. Descarga de PDFs
- Script: `SB_publications/download_pdfs.py` (con estrategias múltiples: EFetch, Europe PMC, parse HTML y resolución de proof‑of‑work (POW)).
- Objetivo: Obtener el PDF real pese al intermediario HTML ("Preparing download" + desafío POW).
- Estado: Capaz de descargar muestras; falta validación masiva y registro de fallidos.
- Riesgos: Cambios futuros en el mecanismo POW pueden romper la lógica.

## 2. Procesamiento con GROBID
- Script batch: `summary/process_grobid_pdfs.py`.
- Flujo:
  1. Itera sobre PDFs en `SB_publications/pdfs/`.
  2. Envía cada PDF al endpoint GROBID (`/api/processFulltextDocument`).
  3. Recibe TEI XML y lo transforma a JSON mediante `summary/parse_grobid.py`.
  4. Guarda salida en `processed_grobid_pdfs/<PMCID>/<PMCID>.grobid.content.json`.
- Estado: Funciona de forma limitada; se observaron salidas vacías / errores (exit codes intermitentes). Falta robustecer reintentos y logging estructurado (ej. JSON log de errores por PMCID).
- Limitaciones actuales del JSON:
  - Puede faltar segmentación completa de secciones si GROBID falla parcial.
  - No se incluyen todavía anotaciones de figuras/tablas en el grafo.

## 3. Construcción del Grafo (kg_creator)
- Módulos principales: `kg_creator/build_graph.py`, `kg_creator/extract_text.py`, `kg_creator/entities.py`.
- Lógica actual (simplificada):
  1. Carga todos los `*.grobid.content.json`.
  2. Concatena título + abstract + texto de secciones (descarta secciones muy cortas).
  3. Aplica heurísticas básicas para entidades:
     - ORGANISM: regex binomio latino `Genus species`.
     - SECTION_CONCEPT: lista cerrada de palabras clave (gene, genome, protein, ...).
     - CHEMICAL: tokens en mayúsculas cortos (muy ruidoso; placeholder).
  4. Crea relaciones `COOCCURS_WITH` entre cada par de entidades de distinto tipo dentro del mismo documento.
- Estado: Extremadamente rudimentario. No hay comprensión semántica, ni desambiguación, ni normalización a ontologías.
- Problemas conocidos:
  - Genera falsos positivos masivos (e.g. tokens en mayúsculas que no son compuestos químicos reales).
  - No diferencia contexto (todo el documento tratado como un bloque único).
  - No representa adecuadamente el contenido específico del PDF cuando el JSON está incompleto.
  - El grafo puede construirse “muy rápido” porque la lógica es trivial y a veces no hay datos reales.

## 4. Exportación e Ingesta en Neo4j
- Exportación CSV: `kg_creator/neo4j_export.py` genera `nodes.csv`, `relations.csv`, `load.cypher`.
- Ingesta directa: `kg_creator/ingest_neo4j.py` (usa variables `.env`, soporte `--wipe`).
- Estado: La ingesta puede terminar sin errores incluso si el grafo está vacío o es irrelevante.
- Riesgo: Sensación de “éxito” engañosa sin validar la calidad ni el volumen de entidades.

---
## Por Qué Actualmente NO es Funcional
1. Cobertura de datos incompleta: No se ha confirmado la conversión correcta de la mayoría de los PDFs.
2. Contenido base posiblemente vacío: Si GROBID falla o devuelve poco texto, el grafo no representa el documento.
3. Heurísticas simplistas: Las reglas actuales no distinguen entidades reales de ruido (
   - No hay modelos biomédicos (NER) ni normalización (MeSH, UMLS, GO, Taxonomy).
4. Relaciones débiles: Co‑ocurrencia a nivel de documento → no representa interacciones ni mecanismos.
5. Ausencia de validación: No hay métricas de densidad, precisión ni verificación manual sistemática.
6. No hay control de versiones de esquema: Estructura mínima sin contrato formal.

---
## Requisitos para Considerarlo Operativo
| Área | Acción Necesaria |
|------|------------------|
| Descarga PDFs | Completar batch, registro de fallidos, checksum opcional |
| Parsing GROBID | Retries robustos, logging estructurado, QA de campos |
| Texto | Segmentación por oración, limpieza referencias |
| Entidades | Integrar SciSpaCy + normalización (UMLS / MeSH / GO / Taxonomy) |
| Relaciones | Patrones lingüísticos + extracción basada en oraciones |
| Ontologías | Diccionarios para genes/proteínas y taxonomía validada |
| Evaluación | Métricas (entidades/doc, relaciones/doc, cobertura palabras clave) |
| Neo4j | Esquema claro (labels y tipos de relación normalizados) |
| Tests | Suite mínima: parsing, extracción, conteo, ingest |

---
## Roadmap Propuesto (Orden Sugerido)
1. Validar y completar generación de todos los `*.grobid.content.json` (etiquetar fallos).
2. Añadir segmentación oracional y filtro de secciones irrelevantes.
3. Integrar SciSpaCy (modelo biomédico) + linker UMLS; almacenar IDs.
4. Definir taxonomía de nodos: (Paper, Section, Organism, Gene/Protein, Process, Chemical, Pathway).
5. Relaciones basadas en co‑ocurrencia por oración + patrones verbales (regulates, inhibits, activates...).
6. Añadir soporte de evidencia: texto original + offsets + hash del enunciado.
7. Mejorar export/ingesta con índices Neo4j (constraints por id). 
8. Métricas QA + panel resumido (JSON/Markdown) tras cada corrida.
9. Opcional: Capa LLM para relaciones complejas (con caching y validación).

---
## Métricas a Incorporar (Pendientes)
- Número de PDFs procesados / total.
- % de PDFs con texto > N palabras.
- Entidades promedio por documento; distribución.
- Relaciones por entidad (grado medio).
- Ratio de entidades sin normalizar.
- Tiempo promedio por PDF.

---
## Riesgos y Mitigaciones
| Riesgo | Impacto | Mitigación |
|--------|---------|------------|
| Cambios en PMC POW | Bloqueo de descargas | Modularizar capa de acceso y fallback APIs alternativas |
| GROBID falla intermitente | Huecos en grafo | Retries + cola diferida + logging estructurado |
| Ruido en entidades heurísticas | Grafo poco útil | Reemplazar heurísticas con NER biomédico + diccionarios |
| Escala en Neo4j (lotes grandes) | Rendimiento | Batch ingest + índices y constraints |
| Falta de evidencias | Difícil auditoría | Guardar snippet oracional y offsets |

---
## Estado Final Actual (Resumen)
> El pipeline **existe como esqueleto**, pero **NO es todavía funcional para análisis biocientífico**. Requiere varias capas de enriquecimiento, validación y normalización antes de ser utilizable.

---
## Próximo Paso Recomendado
Completar y verificar la generación confiable de todos los `*.grobid.content.json` (sin esto, cualquier capa de KG es prematura). Luego incorporar NER biomédico real.

---
*Este documento debe actualizarse conforme se implementen las etapas del roadmap.*
