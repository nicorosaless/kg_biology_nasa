# Objetivo Actual: Visualización Fase 5 estable y mínima

## Estado Actual
- Fase5 en modo minimal genera: `graph_core.json`, `graph_overview.json`, `section_overview.json`, `section_*.json`.
- UI muestra overview (≤40 nodos) + subgrafos de sección con navegación (doble click + panel lateral).
- Counts overview visibles.
- Versión minimalista navegable operativa (overview -> secciones). Falta mejorar calidad estructural (conectividad, diversidad, deduplicación labels, layout cache, sincronización PDF).

## Próximas Acciones (Prioridad)
1. Tooltip enriquecido (label completo, tipo, sección primaria, frecuencia).
2. Mini leyenda fija (color → tipo) sin ocupar más de ~1 línea.
3. Diversidad en overview: cuota mínima por tipo (ej. garantizar presencia si existe de PATHWAY, DISEASE, PHENOTYPE, etc.).
4. Deduplicar labels repetidos (agrupación superficial en overview, mantener IDs en subgrafos).
5. Cache de layout (overview + cada sección) usando localStorage.
 6. En secciones: ya se fuerza conectividad (solo componente gigante) – revisar si necesitamos unir componentes pequeños en vez de descartarlos.

## Siguientes Objetivos Mayores
6. Extraer metadata de página (añadir `page` o `page_index` en `nav`).
7. Sincronización PDF: click nodo -> salto a página/ancla en visor PDF.
8. Integrar visor PDF (pdf.js) con postMessage / ref interno.
9. Script limpieza retroactiva (eliminar restos antiguos en papers previos al cambio).
10. Documentar contrato (README sección “Phase5 Graph Artifacts & Endpoints”).

## Endpoints Requeridos
- GET `/api/paper/{pmcid}/graph/overview`
- GET `/api/paper/{pmcid}/sections`
- GET `/api/paper/{pmcid}/graph/section/{section_name}`

## Futuro (Opcional)
- Comparación multi-sección.
- Export PNG / JSON.
- Edge bundling / reducción para densidad alta.
- Navegación por teclado (Enter abre sección, Backspace vuelve, Arrow keys foco). 

