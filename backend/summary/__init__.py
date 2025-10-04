"""Summary package utilities.

Exporta función de conveniencia `build_summary_and_content` para generar la
carpeta `summary_and_content` de un paper con:
 - <paper_id>.content.json
 - summary.json
 - figures/

CLI relacionado: `python -m summary.paper_summary --pdf <ruta.pdf>`
"""

from .paper_summary import build_summary_and_content  # noqa: F401
