# kg_creator

Pipeline inicial (prototipo) para construir un grafo de conocimiento ligero a partir de los JSON producidos por GROBID (`*.grobid.content.json`).

## Estado actual (HONESTO)
Este módulo es **experimental** y las heurísticas son muy básicas. Lo que hace ahora:
- Carga todos los archivos `processed_grobid_pdfs/**/<PMCID>.grobid.content.json`.
- Concatena título, abstract y texto de secciones (filtrando secciones muy cortas).
- Extrae entidades con reglas simples:
  - ORGANISM: patrón de binomio latino `Genus species` (regex).
  - SECTION_CONCEPT: lista fija de palabras clave (gene, genome, protein, ...).
  - CHEMICAL: tokens en mayúsculas cortos (muy ruidoso / placeholder).
- Genera relaciones `COOCCURS_WITH` entre pares de entidades de distinto tipo dentro del mismo documento (no es basada en oración ni contexto semántico).

Limitaciones actuales:
- No valida que las entidades correspondan a conceptos reales (sin normalización a ontologías / MeSH / GO / NCBI Taxonomy).
- No hay segmentación por oración, lo que produce muchas relaciones falsas.
- No procesa figuras, tablas ni referencias para enriquecer el grafo.
- No hay desambiguación ni fusión avanzada de sinónimos.
- No usa LLMs ni modelos NER científicos (ej. SciSpaCy / BioBERT) todavía.

## Estructura
```
kg_creator/
  extract_text.py     # utilidades para texto
  entities.py         # dataclasses + heurísticas de entidades
  build_graph.py      # construcción del grafo y logging
  neo4j_export.py     # export CSV + script Cypher
  run_kg.py           # CLI orquestador (grafo + export)
  ingest_neo4j.py     # ingesta directa a Neo4j vía Bolt (con --wipe)
```

## Uso rápido
1. Asegúrate de tener JSONs en `processed_grobid_pdfs/<PMCID>/<PMCID>.grobid.content.json`.
2. Construir grafo y exportar CSV:
```bash
python -m kg_creator.run_kg --input processed_grobid_pdfs --graph-out graph.json --neo4j-out neo4j_export
```
3. Ingestar directo a Neo4j (requiere `neo4j` y `.env` con credenciales):
```bash
python -m kg_creator.ingest_neo4j --graph graph.json --wipe
```
4. O usar los CSV copiándolos al directorio `import` de Neo4j y ejecutar `neo4j_export/load.cypher`.

## Variables de entorno (.env)
```
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=********
```

## Mejoras planeadas (roadmap)
1. Descubrimiento de entidades con modelos NER (SciSpaCy) y normalización (UMLS / MeSH / GO).
2. Extracción de relaciones basada en oraciones y patrones lingüísticos (dependency parsing).
3. Incorporar figuras / captions / referencias cruzadas (citas) como nodos adicionales.
4. Detección de genes y proteínas mediante diccionarios externos + case folding.
5. Scoring y filtrado de relaciones por co-ocurrencia estadística (PMI, TF-IDF contextual).
6. Export opcional a formatos RDF (TTL) o GraphML.
7. Integración de graphrag / indexación vectorial para queries semánticas.

## Advertencias
Este grafo NO debe considerarse listo para análisis biológico serio. Es un esqueleto para iterar. Verifica siempre manualmente antes de usarlo en downstream tasks.

## Tests / Calidad
Actualmente no hay suite de tests. Recomendado agregar:
- Pruebas de parsing para un JSON de ejemplo.
- Pruebas de conteo de entidades esperadas sobre texto sintético.

## Contribuir
Crear issues con ejemplos concretos donde las heurísticas fallen para priorizar mejoras.

---
Contacto: abrir un issue con contexto y ejemplos de falsos positivos/negativos.
