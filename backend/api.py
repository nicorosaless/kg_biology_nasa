from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from fastapi.responses import StreamingResponse
import asyncio
import json
from typing import AsyncIterator
import subprocess
import sys
import threading
from pathlib import Path

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

class StartConversationRequest(BaseModel):
	agentId: str
	textOnly: bool | None = False
	toolId: str | None = None
	toolName: str | None = None
	message: str | None = None

@app.post("/api/conversation/start")
def conversation_start(req: StartConversationRequest):
	global _agent_proc
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
	with _proc_lock:
		if not _agent_proc or _agent_proc.poll() is not None:
			_agent_proc = None
			return {"status": "not_running"}
		try:
			_agent_proc.terminate()
		except Exception:
			pass
		finally:
			_agent_proc = None
		return {"status": "stopped"}


@app.get("/api/conversation/status")
def conversation_status():
	with _proc_lock:
		if _agent_proc and _agent_proc.poll() is None:
			return {"running": True, "pid": _agent_proc.pid}
		return {"running": False}


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


if __name__ == "__main__":
	import uvicorn
	uvicorn.run("backend.api:app", host="0.0.0.0", port=8000, reload=True)

