import csv
import requests
import os
import time
import re
import json
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
from typing import Optional, Set

# Nota: El módulo FTP estaba importado pero no se usaba; lo eliminamos para evitar confusión.

BASE_DIR = os.path.dirname(__file__)

# Path to the per-paper CSV (lista completa original)
csv_file = os.path.join(BASE_DIR, 'SB_publication_PMC.csv')

# Path al grafo enriquecido (clusters) para filtrar por macrocluster Radiation & Shielding (C103)
csv_graph_path = os.path.abspath(os.path.join(BASE_DIR, '..', '..', 'frontend', 'public', 'data', 'csvGraph.json'))

# ID del cluster objetivo (Macrocluster: Radiation & Shielding)
CLUSTER_TARGET_ID = 'C103'

# Directorio destino de PDFs: ahora forzado a esta carpeta local dentro de backend.
# Permite override con la variable de entorno PDF_OUTPUT_DIR.
DEFAULT_PDF_DIR = os.path.join(BASE_DIR, 'pdfs')
pdf_dir = os.environ.get('PDF_OUTPUT_DIR', DEFAULT_PDF_DIR)
os.makedirs(pdf_dir, exist_ok=True)

DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'
}

REQUEST_TIMEOUT = 20  # segundos
MAX_RETRIES = 4
BACKOFF_FACTOR = 2  # exponencial: 1,2,4,8...

PMC_HOST_PRIMARY = 'https://pmc.ncbi.nlm.nih.gov'
PMC_HOST_ALT = 'https://www.ncbi.nlm.nih.gov/pmc'

PMC_ID_REGEX = re.compile(r"PMC\d+", re.IGNORECASE)


def load_allowed_pmcs(cluster_id: str = CLUSTER_TARGET_ID) -> Set[str]:
    """Carga el archivo json de clusters y devuelve el set de PMCID que pertenecen al cluster deseado.

    Si el archivo no existe, devuelve set vacío (se reportará en main).
    """
    allowed: Set[str] = set()
    if not os.path.exists(csv_graph_path):
        print(f"[WARN] No se encontró csvGraph.json en {csv_graph_path}; no se aplicará filtrado por cluster")
        return allowed
    try:
        with open(csv_graph_path, 'r', encoding='utf-8') as jf:
            data = json.load(jf)
        papers = data.get('papers', [])
        for p in papers:
            if p.get('clusterId') == cluster_id and 'id' in p:
                # IDs ya vienen como 'PMCxxxx'
                pid = str(p['id']).strip()
                if PMC_ID_REGEX.match(pid):
                    allowed.add(pid.upper())
    except Exception as e:
        print(f"[ERROR] Falló lectura de csvGraph.json: {e}")
    return allowed


def delete_non_cluster_pdfs(allowed: Set[str]):
    """Elimina cualquier PDF existente cuyo nombre (sin .pdf) no esté en el set permitido.
    """
    try:
        for fname in os.listdir(pdf_dir):
            if not fname.lower().endswith('.pdf'):
                continue
            pmc = fname.rsplit('.', 1)[0]
            if pmc.upper() not in allowed:
                fpath = os.path.join(pdf_dir, fname)
                try:
                    os.remove(fpath)
                    print(f"[DEL] {fname} (fuera de cluster {CLUSTER_TARGET_ID})")
                except Exception as e:
                    print(f"[WARN] No se pudo borrar {fname}: {e}")
    except FileNotFoundError:
        # Directorio aún no existe (será creado antes de descargar)
        pass


def extract_pmc_id(link: str) -> Optional[str]:
    """Extrae el identificador PMC completo (e.g. 'PMC3630201')."""
    if not link:
        return None
    match = PMC_ID_REGEX.search(link)
    if match:
        return match.group(0).upper()
    return None


def _request_with_retries(url: str, headers: dict, expect_binary: bool = False) -> Optional[requests.Response]:
    """Realiza una petición GET con reintentos exponenciales en 429/5xx.
    Devuelve Response o None si falla definitivamente.
    """
    delay = 1
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"[WARN] Error de red {e} (intento {attempt}/{MAX_RETRIES}) -> {url}")
            resp = None
        if resp and resp.status_code == 200:
            # Si esperamos binario (PDF), comprobamos que no sea HTML disfrazado (hecho luego fuera)
            return resp
        if resp and resp.status_code in (429, 500, 502, 503, 504):
            print(f"[INFO] Código {resp.status_code} - reintento tras {delay}s ({url})")
            time.sleep(delay)
            delay *= BACKOFF_FACTOR
            continue
        # Otros status -> no reintentar
        if resp:
            print(f"[ERROR] Status {resp.status_code} para {url} (no se reintenta)")
        return None
    return None


PDF_HREF_REGEX = re.compile(r"/pmc/articles/(PMC\d+)/pdf/.+?\.pdf$", re.IGNORECASE)


def get_pdf_url(pmc_id: str) -> Optional[str]:
    """Obtiene la URL directa del PDF para un PMC dado.

    Estrategia:
    1. Descargar página HTML del artículo.
    2. Buscar <link rel="alternate" type="application/pdf" href="...">.
    3. Buscar <a> cuyo texto contenga 'PDF' y href contenga '/pdf/'.
    4. Regex que busque patrones /pmc/articles/PMCxxxxx/pdf/*.pdf.
    5. Fallback: intentar HEAD/GET al patrón base /articles/PMCxxxx/pdf/ y ver si redirige a un PDF real.
    """
    candidate_hosts = [PMC_HOST_PRIMARY, PMC_HOST_ALT]
    article_paths = [f"/articles/{pmc_id}/"]
    article_urls = [urljoin(host, path) for host in candidate_hosts for path in article_paths]

    html_response = None
    article_url_used = None
    for url in article_urls:
        r = _request_with_retries(url, DEFAULT_HEADERS)
        if r and r.status_code == 200 and 'html' in r.headers.get('Content-Type', '').lower():
            html_response = r
            article_url_used = url
            break
    if not html_response:
        print(f"[ERROR] No se pudo obtener HTML del artículo {pmc_id}")
        return None

    soup = BeautifulSoup(html_response.content, 'html.parser')

    # 1. Link alternate
    link_alt = soup.find('link', attrs={'rel': 'alternate', 'type': 'application/pdf'})
    if link_alt and link_alt.get('href') and article_url_used:
        href_val = str(link_alt.get('href'))
        pdf_url = urljoin(article_url_used, href_val)
        if pdf_url.lower().endswith('.pdf'):
            return pdf_url

    # 2 & 3. Anchors con texto PDF y href con /pdf/
    anchor_candidates = []
    for a in soup.find_all('a', href=True):
        text = (a.get_text() or '').strip().lower()
        raw_href = a.get('href')
        href_val = str(raw_href) if raw_href is not None else ''
        if 'pdf' in text or '/pdf/' in href_val.lower():
            anchor_candidates.append(a)

    # Filtrar por regex más específica primero
    for a in anchor_candidates:
        raw_href = a.get('href')
        href_val = str(raw_href) if raw_href is not None else ''
        if href_val and PDF_HREF_REGEX.search(href_val):
            return urljoin(article_url_used or '', href_val)

    # Luego cualquier anchor que termine en .pdf
    for a in anchor_candidates:
        raw_href = a.get('href')
        href_val = str(raw_href) if raw_href is not None else ''
        if href_val.lower().endswith('.pdf'):
            return urljoin(article_url_used or '', href_val)

    # 4. Buscar directamente en todos los hrefs del documento por regex
    for a in soup.find_all('a', href=True):
        raw_href = a.get('href')
        href_val = str(raw_href) if raw_href is not None else ''
        if href_val and PDF_HREF_REGEX.search(href_val):
            return urljoin(article_url_used or '', href_val)

    # 5. Fallback: intentar patrón base /pdf/
    fallback = urljoin(article_url_used or '', 'pdf/')
    r_fb = _request_with_retries(fallback, DEFAULT_HEADERS)
    if r_fb and r_fb.status_code == 200:
        # Si ya es PDF
        ct = r_fb.headers.get('Content-Type', '').lower()
        if 'pdf' in ct or r_fb.content.startswith(b'%PDF'):
            return fallback
        # Si es HTML, parsear por enlaces .pdf allí
        soup_fb = BeautifulSoup(r_fb.content, 'html.parser')
        for a in soup_fb.find_all('a', href=True):
            raw_href = a.get('href')
            href_val = str(raw_href) if raw_href is not None else ''
            if href_val.lower().endswith('.pdf') or '/pdf/' in href_val.lower():
                return urljoin(fallback, href_val)

    print(f"[WARN] No se encontró URL PDF para {pmc_id}")
    return None

def download_pdf(pmc_id: str, title: str) -> None:
    """Descarga el PDF para un PMCID.

    - Evita descargar si ya existe el archivo.
    - Usa extracción robusta de URL del PDF.
    - Verifica que el contenido comience con %PDF.
    """
    filename = f"{pmc_id}.pdf"
    filepath = os.path.join(pdf_dir, filename)
    if os.path.exists(filepath) and os.path.getsize(filepath) > 5_000:  # heurística mínimo tamaño
        print(f"[SKIP] Ya existe {filename}")
        return

    # 1) Intentar EFetch (db=pmc) con id numérico
    pmc_numeric = pmc_id.replace('PMC','')
    efetch_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmc_numeric}&rettype=pdf"
    r_efetch = _request_with_retries(efetch_url, DEFAULT_HEADERS, expect_binary=True)
    if r_efetch and r_efetch.content.startswith(b'%PDF'):
        with open(filepath,'wb') as f_out:
            f_out.write(r_efetch.content)
        print(f"[OK][EFETCH] {pmc_id} -> {filename} ({len(r_efetch.content)//1024} KB)")
        return

    # 2) Intentar Europe PMC (a veces provee PDF directo). Formato: https://www.ebi.ac.uk/europepmc/webservices/rest/PMC3630201/fullTextPDF
    eu_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmc_id}/fullTextPDF"
    r_eu = _request_with_retries(eu_url, DEFAULT_HEADERS, expect_binary=True)
    if r_eu and r_eu.content.startswith(b'%PDF'):
        with open(filepath,'wb') as f_out:
            f_out.write(r_eu.content)
        print(f"[OK][EUROPEPMC] {pmc_id} -> {filename} ({len(r_eu.content)//1024} KB)")
        return

    pdf_url = get_pdf_url(pmc_id)
    if not pdf_url:
        return
    pdf_headers = {**DEFAULT_HEADERS, 'Accept': 'application/pdf', 'Referer': pdf_url.rsplit('/pdf/', 1)[0] if '/pdf/' in pdf_url else pdf_url}
    resp = _request_with_retries(pdf_url, pdf_headers, expect_binary=True)
    if not resp:
        print(f"[ERROR] No se pudo descargar {pmc_id} (fallo de red)")
        return

    def save_pdf(r: requests.Response) -> bool:
        if not (r.content.startswith(b'%PDF') or 'pdf' in r.headers.get('Content-Type', '').lower()):
            return False
        with open(filepath, 'wb') as f_out:
            f_out.write(r.content)
        print(f"[OK] {pmc_id} -> {filename} ({len(r.content)//1024} KB)")
        return True

    if save_pdf(resp):
        return

    # Si llegó aquí es HTML: intentar localizar redirecciones / enlaces internos.
    soup_pdf = BeautifulSoup(resp.content, 'html.parser')

    # 1. meta refresh
    meta = soup_pdf.find('meta', attrs={'http-equiv': re.compile('refresh', re.IGNORECASE)})
    if meta and meta.get('content'):
        # content="0; url=..."
        meta_content = str(meta.get('content'))
        parts = meta_content.split(';')
        for part in parts:
            if 'url=' in part.lower():
                target = part.split('=', 1)[1].strip().strip('"')
                new_url = urljoin(pdf_url, target)
                r2 = _request_with_retries(new_url, pdf_headers, expect_binary=True)
                if r2 and save_pdf(r2):
                    return

    # 2. iframe con src a pdf
    iframe = soup_pdf.find('iframe', src=True)
    if iframe:
        iframe_src = str(iframe['src'])
        if iframe_src.lower().endswith('.pdf') or 'pdf' in iframe_src.lower():
            new_url = urljoin(pdf_url, iframe_src)
            r2 = _request_with_retries(new_url, pdf_headers, expect_binary=True)
            if r2 and save_pdf(r2):
                return

    # 3. enlaces dentro del HTML que terminen en .pdf
    for a in soup_pdf.find_all('a', href=True):
        h = str(a.get('href') or '')
        if h.lower().endswith('.pdf'):
            new_url = urljoin(pdf_url, h)
            r2 = _request_with_retries(new_url, pdf_headers, expect_binary=True)
            if r2 and save_pdf(r2):
                return

    # 4. Intentar POW (Proof-of-Work) si hay variables POW_CHALLENGE en el HTML
    script_text = resp.text
    m_challenge = re.search(r'POW_CHALLENGE\s*=\s*"([^"]+)"', script_text)
    m_diff = re.search(r'POW_DIFFICULTY\s*=\s*"(\d+)"', script_text)
    if m_challenge:
        challenge = m_challenge.group(1)
        difficulty = int(m_diff.group(1)) if m_diff else 4
        prefix = '0' * difficulty
        import hashlib
        nonce = 0
        # Bucle de búsqueda (dificultad 4 es rápido)
        while True:
            candidate = challenge + str(nonce)
            h = hashlib.sha256(candidate.encode()).hexdigest()
            if h.startswith(prefix):
                break
            nonce += 1
        pow_cookie = f"cloudpmc-viewer-pow={challenge},{nonce}"
        pow_headers = {**pdf_headers, 'Cookie': pow_cookie}
        r_pow = _request_with_retries(pdf_url, pow_headers, expect_binary=True)
        if r_pow and save_pdf(r_pow):
            return
    # 5. Variante ?download=1 después del POW
    if '?' in pdf_url:
        alt_url = pdf_url + '&download=1'
    else:
        alt_url = pdf_url + '?download=1'
    r2 = _request_with_retries(alt_url, pdf_headers, expect_binary=True)
    if r2 and save_pdf(r2):
        return

    print(f"[ERROR] Respuesta no es PDF para {pmc_id}: Content-Type={resp.headers.get('Content-Type')} url={pdf_url}")

def main(limit: Optional[int] = 5, enforce_cluster: bool = True):
    allowed = load_allowed_pmcs() if enforce_cluster else set()
    if enforce_cluster and not allowed:
        print(f"[WARN] Set de PMCs permitido vacío (cluster {CLUSTER_TARGET_ID}); no se descargarán PDFs nuevos.")
    else:
        print(f"[INFO] PMCs permitidos en cluster {CLUSTER_TARGET_ID}: {len(allowed)}")

    # Limpieza de PDFs fuera del cluster antes de comenzar
    if enforce_cluster:
        delete_non_cluster_pdfs(allowed)

    processed = 0
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        print("Columnas:", reader.fieldnames)
        for row in reader:
            link = row.get('Link')
            title = row.get('Title', '')
            link_str = link if isinstance(link, str) else (str(link) if link is not None else '')
            pmc_id = extract_pmc_id(link_str) if link_str else None
            if not pmc_id:
                print(f"[WARN] No se pudo extraer PMCID de {link}")
            else:
                if (not enforce_cluster) or (pmc_id in allowed):
                    download_pdf(pmc_id, title)
                else:
                    # Si existe el archivo y no está permitido ya habrá sido borrado al inicio; solo informar skip lógico.
                    print(f"[SKIP] {pmc_id} fuera de cluster {CLUSTER_TARGET_ID}")
            processed += 1
            time.sleep(0.4)  # un poco más ágil pero aún respetuoso
            if limit is not None and processed >= limit:
                break
    print("Proceso de descarga finalizado.")


if __name__ == '__main__':
    # Ajusta 'limit=None' para procesar todos los artículos. Filtrado de cluster activado por defecto.
    main(limit=None, enforce_cluster=True)