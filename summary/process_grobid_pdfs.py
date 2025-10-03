"""Procesa en lote los PDFs de SB_publications/pdfs usando GROBID y genera:
 - TEI XML crudo (*.tei.xml)
 - JSON parseado (*.grobid.content.json) reutilizando parse_grobid.save_content_json

Requisitos previos:
1. Tener el servidor GROBID corriendo localmente (por defecto en http://localhost:8070)
   Ejemplo rápido (si usas docker):
       docker run --rm -p 8070:8070 lfoppiano/grobid:0.8.0
2. Instalar dependencia grobid_client (pip install grobid-client)

Uso:
    python process_grobid_pdfs.py --pdf-dir SB_publications/pdfs --out-dir processed_grobid_pdfs 
    # Añadir --limit 5 para prueba rápida.

Idempotencia: salta PDFs ya procesados (si existe JSON y no se fuerza --force).
"""
from __future__ import annotations
import argparse
from pathlib import Path
import json
import time
import sys
from typing import Optional

USE_GROBID_CLIENT = True
try:  # Intentar importar grobid_client; si falla, usar fallback HTTP simple
    from grobid_client.grobid_client import GrobidClient  # type: ignore
except Exception:
    GrobidClient = None  # type: ignore
    USE_GROBID_CLIENT = False

# Import local parser (parse_grobid.py está en la misma carpeta summary)
sys.path.append(str(Path(__file__).parent))
try:
    from parse_grobid import save_content_json  # type: ignore
except ImportError:
    print("ERROR: No se pudo importar parse_grobid. Verifica que 'summary/parse_grobid.py' exista.")
    raise

if not USE_GROBID_CLIENT:
    print("[INFO] grobid_client no disponible; usando fallback HTTP con requests.")
    import requests

DEFAULT_SERVER = 'http://localhost:8070'

def process_pdf(client, pdf_path: Path, out_dir: Path, force: bool = False, sleep: float = 0.3, server_url: str = DEFAULT_SERVER, keep_tei: bool = False) -> bool:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    pdf_dir = out_dir / stem
    pdf_dir.mkdir(parents=True, exist_ok=True)
    tei_path = pdf_dir / f"{stem}.tei.xml"
    json_path = pdf_dir / f"{stem}.grobid.content.json"
    if not force and json_path.exists() and json_path.stat().st_size > 500:
        print(f"[SKIP] {stem} ya procesado")
        if not keep_tei and tei_path.exists():
            try: tei_path.unlink()
            except OSError: pass
        return True
    try:
        if USE_GROBID_CLIENT:
            _, status, tei = client.process_pdf(
                pdf_file=str(pdf_path),
                service='processFulltextDocument',
                generateIDs=False,
                consolidate_header=False,
                consolidate_citations=False,
                include_raw_citations=True,
                include_raw_affiliations=True,
                tei_coordinates=True,
                segment_sentences=True
            )
            if status != 200 or not tei or not tei.startswith('<'):
                print(f"[ERROR] Fallo GROBID {stem} status={status}")
                return False
        else:
            # Fallback simple: POST multipart a /api/processFulltextDocument
            import requests
            with pdf_path.open('rb') as fh:
                files = {'input': (pdf_path.name, fh, 'application/pdf')}
                data = {
                    'generateIDs': '0',
                    'consolidateHeader': '0',
                    'consolidateCitations': '0',
                    'includeRawCitations': '1',
                    'includeRawAffiliations': '1',
                    'teiCoordinates': '1',
                    'segmentSentences': '1'
                }
                resp = requests.post(f"{server_url}/api/processFulltextDocument", files=files, data=data, timeout=120)
            if resp.status_code != 200 or not resp.text.startswith('<'):
                print(f"[ERROR] Fallo GROBID (fallback) {stem} status={resp.status_code}")
                return False
            tei = resp.text
        if keep_tei:
            tei_path.write_text(tei, encoding='utf-8')
        # Guardar JSON directamente en la subcarpeta pdf_dir
        save_content_json(pdf_path, tei, pdf_dir)
        # Si no se desea TEI y fue escrito por un intento previo, eliminar
        if not keep_tei and tei_path.exists():
            try: tei_path.unlink()
            except OSError: pass
        print(f"[OK] {stem}")
        time.sleep(sleep)
        return True
    except Exception as e:  # pragma: no cover
        print(f"[EXCEPTION] {stem}: {e}")
        return False

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pdf-dir', default='SB_publications/pdfs', help='Directorio con PDFs')
    ap.add_argument('--out-dir', default='processed_grobid_pdfs', help='Directorio de salida TEI+JSON')
    ap.add_argument('--server-url', default=DEFAULT_SERVER, help='URL servidor GROBID')
    ap.add_argument('--limit', type=int, default=None, help='Limitar número de PDFs (debug)')
    ap.add_argument('--force', action='store_true', help='Reprocesar aunque exista JSON')
    ap.add_argument('--reverse', action='store_true', help='Procesar en orden inverso')
    ap.add_argument('--keep-tei', action='store_true', help='Conservar archivo TEI XML (por defecto se descarta)')
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    out_dir = Path(args.out_dir)
    if not pdf_dir.exists():
        print(f"ERROR: No existe directorio PDFs {pdf_dir}")
        sys.exit(1)

    # Preparar client o validar que el servidor vive
    client = None
    if USE_GROBID_CLIENT and GrobidClient is not None:
        client = GrobidClient(grobid_server=args.server_url, check_server=False)
        is_up, _ = client.ping()
        if not is_up:
            print(f"ERROR: GROBID no responde en {args.server_url}")
            sys.exit(2)
    else:
        # Fallback: simple ping HTTP
        import requests
        try:
            r = requests.get(f"{args.server_url}/api/isalive", timeout=10)
            if r.status_code != 200:
                print(f"ERROR: GROBID no responde correctamente en {args.server_url} (status {r.status_code})")
                sys.exit(2)
        except requests.RequestException as e:
            print(f"ERROR: No se pudo conectar a GROBID en {args.server_url}: {e}")
            sys.exit(2)

    pdf_files = sorted([p for p in pdf_dir.glob('*.pdf') if p.is_file()])
    if args.reverse:
        pdf_files = list(reversed(pdf_files))
    if args.limit is not None:
        pdf_files = pdf_files[:args.limit]

    total = len(pdf_files)
    ok, fail = 0, 0
    for idx, pdf in enumerate(pdf_files, start=1):
        print(f"[{idx}/{total}] Procesando {pdf.name}")
        if process_pdf(client, pdf, out_dir, force=args.force, server_url=args.server_url, keep_tei=args.keep_tei):
            ok += 1
        else:
            fail += 1
    summary = {'total': total, 'ok': ok, 'fail': fail}
    (out_dir / 'batch_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Resumen: {summary}")
    if fail:
        sys.exit(3)
    sys.exit(0)

if __name__ == '__main__':
    main()
