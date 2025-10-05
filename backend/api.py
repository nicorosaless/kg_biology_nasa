from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import asyncio
import json
from typing import AsyncIterator, Dict, Any, Optional
import subprocess
import sys
import threading
from pathlib import Path
import re

# --- Paths & constants for pipeline artifacts ---
REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
PDF_DIR = BACKEND_DIR / 'SB_publications' / 'pdfs'
# Adjusted: processed outputs are now expected under backend/processed_grobid_pdfs
BASE_PROCESSED_DIR = BACKEND_DIR / 'processed_grobid_pdfs'
PMC_PATTERN = re.compile(r'^PMC\d+$', re.IGNORECASE)

def _norm_pmcid(pmcid: str) -> str:
	pmcid = pmcid.strip()
	if not pmcid.upper().startswith('PMC'):
		pmcid = 'PMC' + pmcid
	pmcid = pmcid.upper()
	if not PMC_PATTERN.match(pmcid):
		raise HTTPException(status_code=400, detail='Invalid PMCID format')
	return pmcid

# Simple in-memory cache for quick status lookups
PIPELINE_CACHE: Dict[str, Dict[str, Any]] = {}

def _paper_dirs(pmcid: str) -> Dict[str, Path]:
	root = BASE_PROCESSED_DIR / pmcid
	sac = root / 'summary_and_content'
	graph_phase5 = root / 'graph' / 'phase5'
	return {
		'root': root,
		'sac': sac,
		'summary_json': sac / 'summary.json',
		'content_json': sac / f'{pmcid}.content.json',
		'figures_dir': sac / 'figures',
		'graph_phase5': graph_phase5,
		'graph_core': graph_phase5 / 'graph_core.json',
		'graph_full': graph_phase5 / 'graph.json',
		'graph_vis': graph_phase5 / 'graph_vis.json',
		'section_overview': graph_phase5 / 'section_overview.json'
	}

def _read_json(path: Path) -> Any:
	try:
		return json.loads(path.read_text(encoding='utf-8'))
	except Exception:
		raise HTTPException(status_code=500, detail=f'Failed reading {path.name}')

def _ensure_pipeline(pmcid: str, overwrite: bool = False, force_kg: bool = False) -> Dict[str, Any]:
	"""Run full pipeline if needed (or cached). Returns summary metadata.
	We invoke full_pipeline.py as a subprocess to avoid import side-effects.
	"""
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	need_summary = overwrite or not (dirs['summary_json'].exists() and dirs['content_json'].exists())
	need_graph = force_kg or not dirs['graph_core'].exists()
	if not need_summary and not need_graph and pmcid in PIPELINE_CACHE:
		return PIPELINE_CACHE[pmcid]
	# Build command
	cmd = [
		sys.executable,
		str(BACKEND_DIR / 'full_pipeline.py'),
		'--pdf', str(PDF_DIR / f'{pmcid}.pdf'),
		'--paper-id', pmcid,
		'--base-dir', str(BASE_PROCESSED_DIR)
	]
	if overwrite:
		cmd.append('--overwrite')
	if need_graph:
		cmd.append('--force-kg')
	# Run subprocess (blocking)
	try:
		proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60*20)
	except subprocess.TimeoutExpired:
		raise HTTPException(status_code=504, detail='Pipeline timeout')
	if proc.returncode != 0:
		raise HTTPException(status_code=500, detail=f'Pipeline failed: {proc.stdout or proc.stderr}')
	try:
		payload = json.loads(proc.stdout)
		paper_entry = next((p for p in payload.get('papers', []) if p.get('paper_id') == pmcid), {})
	except Exception:
		paper_entry = {}
	PIPELINE_CACHE[pmcid] = paper_entry or {'paper_id': pmcid}
	return PIPELINE_CACHE[pmcid]

import tempfile

app = FastAPI(title="KG Biology NASA API", version="0.1.0")

# Allow common local dev origins; override with FRONTEND_ORIGIN if needed
default_origins = {
    "http://localhost:8080",
    "http://127.0.0.1:8080",
	"http://localhost:8081",
	"http://127.0.0.1:8081",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
extra = os.getenv("FRONTEND_ORIGIN")
if extra:
    default_origins.add(extra)
app.add_middleware(
	CORSMiddleware,
	allow_origins=list(default_origins),
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


@app.get("/health")
def health():
	return {"status": "ok"}


class TokenRequest(BaseModel):
	agentId: str


@app.post("/api/elevenlabs/token")
def elevenlabs_token(req: TokenRequest):
	# Stub for local dev; replace with real token minting if needed
	return {"token": "local-dev-token", "agentId": req.agentId}


# --- Agent process management (start/stop) ---
_proc_lock = threading.Lock()
_agent_proc: subprocess.Popen | None = None
_agent_fifo_path: str | None = None

class StartConversationRequest(BaseModel):
	agentId: str
	textOnly: bool | None = False
	toolId: str | None = None
	toolName: str | None = None
	message: str | None = None

@app.post("/api/conversation/start")
def conversation_start(req: StartConversationRequest):
	global _agent_proc
	global _agent_fifo_path
	with _proc_lock:
		if _agent_proc and _agent_proc.poll() is None:
			return {"status": "already_running", "pid": _agent_proc.pid}

		# Build command to run start_agent.py
		root = Path(__file__).resolve().parent
		agent_dir = root / "VoiceAgent"
		script = agent_dir / "start_agent.py"
		if not script.exists():
			raise HTTPException(status_code=500, detail=f"Agent script not found at {script}")

		env = os.environ.copy()
		env["LOG_CONVERSATION"] = "1"
		env["AGENT_ID"] = req.agentId
		# Play agent audio back while capturing user in browser via STT
		env["OUTPUT_ONLY"] = "1"
		# Create a fifo for text ingress
		tmpdir = tempfile.gettempdir()
		_agent_fifo_path = str(Path(tmpdir) / f"agent_inbox_{os.getpid()}.fifo")
		try:
			if os.path.exists(_agent_fifo_path):
				os.remove(_agent_fifo_path)
			os.mkfifo(_agent_fifo_path)
			env["INBOX_FIFO"] = _agent_fifo_path
		except Exception:
			_agent_fifo_path = None
		# Optional: pass ELEVENLABS_API_KEY from environment if present
		# If your agent is private, set ELEVENLABS_API_KEY in the backend environment before starting the server
		args: list[str] = [sys.executable, str(script)]
		if req.textOnly:
			env["TEXT_ONLY"] = "1"
		if req.toolId:
			args += ["--tool-id", req.toolId]
		if req.toolName:
			args += ["--tool-name", req.toolName]
		if req.message:
			args += ["--message", req.message]

		try:
			_agent_proc = subprocess.Popen(
				args,
				cwd=str(agent_dir),
				env=env,
				stdout=subprocess.PIPE,
				stderr=subprocess.STDOUT,
				text=True,
				start_new_session=True,
			)
		except Exception as e:
			_agent_proc = None
			raise HTTPException(status_code=500, detail=f"Failed to start agent: {e}")

		return {"status": "started", "pid": _agent_proc.pid}


@app.post("/api/conversation/stop")
def conversation_stop():
	global _agent_proc
	global _agent_fifo_path
	with _proc_lock:
		if not _agent_proc or _agent_proc.poll() is not None:
			_agent_proc = None
			if _agent_fifo_path and os.path.exists(_agent_fifo_path):
				try:
					os.remove(_agent_fifo_path)
				except Exception:
					pass
			_agent_fifo_path = None
			return {"status": "not_running"}
		try:
			_agent_proc.terminate()
		except Exception:
			pass
		finally:
			_agent_proc = None
			if _agent_fifo_path and os.path.exists(_agent_fifo_path):
				try:
					os.remove(_agent_fifo_path)
				except Exception:
					pass
			_agent_fifo_path = None
		return {"status": "stopped"}


@app.get("/api/conversation/status")
def conversation_status():
	with _proc_lock:
		if _agent_proc and _agent_proc.poll() is None:
			return {"running": True, "pid": _agent_proc.pid}
		return {"running": False}


class SendMessageRequest(BaseModel):
	text: str

@app.post("/api/conversation/send")
def conversation_send(req: SendMessageRequest):
	# Write a single line to the FIFO; the agent thread will forward to Conversation
	with _proc_lock:
		if not _agent_proc or _agent_proc.poll() is not None:
			raise HTTPException(status_code=400, detail="Agent not running")
		if not _agent_fifo_path or not os.path.exists(_agent_fifo_path):
			raise HTTPException(status_code=500, detail="FIFO unavailable")
	try:
		with open(_agent_fifo_path, "w", encoding="utf-8") as f:
			f.write(req.text.strip() + "\n")
		return {"status": "ok"}
	except Exception as e:
		raise HTTPException(status_code=500, detail=f"Failed to send message: {e}")


# SSE stream of conversation logs written by backend/VoiceAgent/start_agent.py when LOG_CONVERSATION=1
async def tail_file(path: str) -> AsyncIterator[bytes]:
	# naive file tailer for dev; not production-grade
	pos = 0
	try:
		while True:
			await asyncio.sleep(0.5)
			if not os.path.exists(path):
				continue
			size = os.path.getsize(path)
			if size < pos:
				pos = 0
			if size > pos:
				with open(path, "rb") as f:
					f.seek(pos)
					chunk = f.read()
					pos = f.tell()
				for line in chunk.splitlines():
					try:
						data = json.loads(line.decode("utf-8"))
						yield f"data: {json.dumps(data)}\n\n".encode("utf-8")
					except Exception:
						continue
	except asyncio.CancelledError:
		return


@app.get("/api/conversation/stream")
async def conversation_stream():
	log_path = os.path.join(os.path.dirname(__file__), "VoiceAgent", "logs", "active.jsonl")
	headers = {
		"Cache-Control": "no-cache",
		"Connection": "keep-alive",
		"X-Accel-Buffering": "no",
	}
	return StreamingResponse(tail_file(log_path), media_type="text/event-stream", headers=headers)

# ------------------- Paper / Pipeline Endpoints -------------------

@app.get('/api/papers')
def list_papers(limit: int = 0):
	"""List available PDF paper IDs (cluster already filtered by prior download stage)."""
	if not PDF_DIR.exists():
		return {'papers': []}
	ids = [p.stem for p in sorted(PDF_DIR.glob('PMC*.pdf'))]
	if limit > 0:
		ids = ids[:limit]
	return {'papers': ids, 'count': len(ids)}

class ProcessRequest(BaseModel):
	overwrite: bool = False
	force_kg: bool = False

@app.post('/api/paper/{pmcid}/process')
def process_paper(pmcid: str, body: ProcessRequest):
	pmcid = _norm_pmcid(pmcid)
	# quick existence check
	if not (PDF_DIR / f'{pmcid}.pdf').exists():
		raise HTTPException(status_code=404, detail='PDF not found')
	meta = _ensure_pipeline(pmcid, overwrite=body.overwrite, force_kg=body.force_kg)
	return {'paper': meta, 'status': 'processed'}

@app.get('/api/paper/{pmcid}/status')
def paper_status(pmcid: str):
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	return {
		'paper_id': pmcid,
		'summary_exists': dirs['summary_json'].exists(),
		'graph_exists': dirs['graph_core'].exists(),
		'cached': pmcid in PIPELINE_CACHE
	}

@app.get('/api/paper/{pmcid}/summary')
def get_summary(pmcid: str, run: bool = False):
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	if run and not dirs['summary_json'].exists():
		_ensure_pipeline(pmcid)
	if not dirs['summary_json'].exists():
		raise HTTPException(status_code=404, detail='Summary not found')
	return _read_json(dirs['summary_json'])

@app.get('/api/paper/{pmcid}/content')
def get_content(pmcid: str):
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	if not dirs['content_json'].exists():
		raise HTTPException(status_code=404, detail='Content not found')
	return _read_json(dirs['content_json'])

@app.get('/api/paper/{pmcid}/graph')
def get_graph(pmcid: str, core: bool = True, run: bool = False):
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	if run and not dirs['graph_core'].exists():
		_ensure_pipeline(pmcid, force_kg=True)
	target = dirs['graph_core'] if core else dirs['graph_full']
	if not target.exists():
		raise HTTPException(status_code=404, detail='Graph not found')
	return _read_json(target)

@app.get('/api/paper/{pmcid}/sections')
def get_sections(pmcid: str):
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	overview = dirs['section_overview']
	if not overview.exists():
		raise HTTPException(status_code=404, detail='Section overview not found')
	return _read_json(overview)

@app.get('/api/paper/{pmcid}/pdf')
def get_pdf(pmcid: str, download: bool = False):
	"""Return PDF inline by default to allow in-browser rendering.

	Pass ?download=1 to force browser download (attachment).
	"""
	pmcid = _norm_pmcid(pmcid)
	pdf_path = PDF_DIR / f'{pmcid}.pdf'
	if not pdf_path.exists():
		raise HTTPException(status_code=404, detail='PDF not found')
	disposition = 'attachment' if download else 'inline'
	headers = {"Content-Disposition": f'{disposition}; filename="{pmcid}.pdf"'}
	# Do NOT pass filename param, which would force attachment by FastAPI defaults
	return FileResponse(str(pdf_path), media_type='application/pdf', headers=headers)

@app.get('/api/paper/{pmcid}/figures/{name}')
def get_figure(pmcid: str, name: str):
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	fig_path = dirs['figures_dir'] / name
	if not fig_path.exists():
		raise HTTPException(status_code=404, detail='Figure not found')
	# naive content-type detection; could refine
	return FileResponse(str(fig_path))

@app.get('/api/paper/{pmcid}/figures')
def list_figures(pmcid: str):
	"""List figure image filenames for a processed paper."""
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	if not dirs['figures_dir'].exists():
		raise HTTPException(status_code=404, detail='Figures directory not found')
	figs = [f.name for f in sorted(dirs['figures_dir'].glob('*')) if f.is_file()]
	return {'paper_id': pmcid, 'figures': figs, 'count': len(figs)}

@app.get('/api/paper/{pmcid}/graph/section/{section_name}')
def get_section_graph(pmcid: str, section_name: str):
	"""Return a section-level subgraph JSON (phase5 section_*.json). section_name is matched case-insensitively against filename pattern after the numeric index.

	Example: section_name=ABSTRACT -> loads file whose name contains '_ABSTRACT'.
	"""
	pmcid = _norm_pmcid(pmcid)
	dirs = _paper_dirs(pmcid)
	phase5 = dirs['graph_phase5']
	if not phase5.exists():
		raise HTTPException(status_code=404, detail='Phase5 graph directory not found')
	# Normalize section_name for matching
	target_key = section_name.strip().lower().replace(' ', '-')
	candidates = list(phase5.glob('section_*.json'))
	chosen = None
	for c in candidates:
		base = c.stem  # section_01_Animals
		# remove leading index: section_\d+_
		parts = base.split('_', 2)
		# parts: ['section', '01', 'Animals'] or longer
		if len(parts) >= 3:
			sec_part = parts[2].lower()
		else:
			sec_part = base.lower()
		# also create a hyphen variant
		hyphen_variant = sec_part.replace(' ', '-').replace('--', '-')
		if target_key in (sec_part, hyphen_variant):
			chosen = c
			break
		# fallback: contains
		if target_key in sec_part:
			chosen = c
			break
	if not chosen:
		raise HTTPException(status_code=404, detail=f'Section graph not found for {section_name}')
	try:
		return _read_json(chosen)
	except HTTPException:
		raise
	except Exception:
		raise HTTPException(status_code=500, detail='Failed reading section graph')


if __name__ == "__main__":
	import uvicorn
	uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)

