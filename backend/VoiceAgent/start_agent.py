import os
import signal
import time
from typing import Optional
import json
from datetime import datetime

# Lightweight JSONL logger so the frontend can stream conversation logs if desired.
LOG_CONV = os.getenv("LOG_CONVERSATION") == "1"
LOG_PATH = os.getenv("LOG_PATH") or os.path.join(os.path.dirname(__file__), "logs", "active.jsonl")

def iso_now() -> str:
  return datetime.utcnow().isoformat() + "Z"

def log_event(obj: dict):
  if not LOG_CONV:
    return
  try:
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
      f.write(json.dumps(obj, ensure_ascii=False) + "\n")
  except Exception:
    pass

def log_event_safe(obj: dict):
  try:
    log_event(obj)
  except Exception:
    pass

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation
from elevenlabs.conversational_ai.conversation import ClientTools
try:
    from elevenlabs.conversational_ai.default_audio_interface import DefaultAudioInterface  # type: ignore
    _has_audio = True
except Exception:
    DefaultAudioInterface = None  # type: ignore
    _has_audio = False

# Optional: sounddevice-based audio interface (no PyAudio required)
class SDIAudioInterface:
  INPUT_FRAMES_PER_BUFFER = 4000  # 250ms @ 16kHz
  OUTPUT_FRAMES_PER_BUFFER = 1000  # 62.5ms @ 16kHz

  def __init__(self):
    import sounddevice as sd  # type: ignore
    import queue, threading
    self.sd = sd
    self.queue = queue
    self.threading = threading
    # Use object queue so we can send a None sentinel to stop cleanly
    self.output_queue: queue.Queue[object] = queue.Queue()
    self.should_stop = threading.Event()
    self.input_callback = None

  def start(self, input_callback):
    self.input_callback = input_callback

    def in_callback(indata, frames, time_info, status):
      # indata is float32; convert to int16 PCM 16k mono
      data = (indata[:, 0] * 32767.0).astype('int16').tobytes()
      if self.input_callback:
        self.input_callback(data)
    self.in_stream = self.sd.InputStream(
      channels=1, samplerate=16000, dtype='float32', callback=in_callback,
      blocksize=self.INPUT_FRAMES_PER_BUFFER
    )

    self.out_stream = self.sd.OutputStream(
      channels=1, samplerate=16000, dtype='int16', blocksize=self.OUTPUT_FRAMES_PER_BUFFER
    )

    self.in_stream.start()
    self.out_stream.start()

    def output_thread():
      import queue
      import numpy as np
      while not self.should_stop.is_set():
        try:
          audio = self.output_queue.get(timeout=0.25)
        except queue.Empty:
          pass
        else:
          if audio is None:
            # Sentinel to stop thread
            break
          try:
            # Convert raw PCM16 bytes to numpy int16 array for sounddevice
            if isinstance(audio, (bytes, bytearray)):
              np_audio = np.frombuffer(audio, dtype=np.int16)
            else:
              np_audio = audio
            self.out_stream.write(np_audio)
          except Exception:
            # Stream likely closing or device error; exit thread
            break
    self.thread = self.threading.Thread(target=output_thread, daemon=True)
    self.thread.start()

  def stop(self):
    self.should_stop.set()
    try:
      # Unblock writer thread if waiting
      try:
        self.output_queue.put_nowait(None)
      except Exception:
        pass
      self.thread.join(timeout=1.0)
    except Exception:
      pass
    try:
      # Stop streams after thread exited to avoid race
      self.in_stream.stop(); self.in_stream.close()
      self.out_stream.stop(); self.out_stream.close()
    except Exception:
      pass

  def output(self, audio: bytes):
    if not self.should_stop.is_set():
      self.output_queue.put(audio)

  def interrupt(self):
    try:
      while True:
        _ = self.output_queue.get(block=False)
    except Exception:
      pass

# Configure SSL certificates for macOS Python if needed
try:
  import certifi  # type: ignore
  os.environ.setdefault("SSL_CERT_FILE", certifi.where())
  os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except Exception:
  pass

# Minimal no-op audio interface for text-only sessions
class NullAudioInterface:
  def __init__(self):
    self.input_callback = None
    self.should_stop = False

  def start(self, input_callback=None):
    # Store the callback; in text-only mode we don't capture mic
    self.input_callback = input_callback

  def stop(self):
    self.should_stop = True

  def output(self, audio: bytes):
    # Drop audio in text-only mode
    return

  def interrupt(self):
    # No-op for text-only
    return

# Custom ClientTools to log tool calls/results and gracefully handle unknown tools
class PrintingClientTools(ClientTools):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def execute_tool(self, tool_name: str, parameters: dict, callback):  # type: ignore[override]
    # Wrap the callback so we can also print the tool result locally
    def wrapped_callback(response: dict):
      # Print concise tool result to console
      result_preview = response.get("result")
      # Truncate noisy content but keep useful info
      text = str(result_preview)
      if isinstance(result_preview, (bytes, bytearray)):
        text = f"<{len(result_preview)} bytes>"
      elif len(text) > 800:
        text = text[:800] + "..."
      print(f"Tool [{tool_name}] -> {text}")
      try:
        log_event({
          "ts": iso_now(),
          "type": "tool",
          "tool": tool_name,
          # Log the original parameters provided to the tool call (excluding tool_call_id)
          "parameters": {k: v for k, v in (parameters or {}).items() if k != "tool_call_id"},
          "result": text,
        })
      except Exception:
        pass
      return callback(response)

    # If the tool is registered, use the normal flow
    with self.lock:
      is_known = tool_name in self.tools

    if is_known:
      return super().execute_tool(tool_name, parameters, wrapped_callback)

    # Unknown tool: provide a safe default echo result so the agent doesn't break
    if not self._running.is_set() or self._loop is None:
      raise RuntimeError("ClientTools event loop is not running")

    async def _default_and_callback():
      try:
        response = {
          "type": "client_tool_result",
          "tool_call_id": parameters.get("tool_call_id"),
          "result": {
            "message": "Client received tool call but no local handler is registered.",
            "tool_name": tool_name,
            "parameters": {k: v for k, v in parameters.items() if k != "tool_call_id"},
          },
          "is_error": False,
        }
      except Exception as e:
        response = {
          "type": "client_tool_result",
          "tool_call_id": parameters.get("tool_call_id"),
          "result": str(e),
          "is_error": True,
        }
      wrapped_callback(response)

    # Schedule on our event loop
    if self._custom_loop is not None:
      return self._loop.create_task(_default_and_callback())
    else:
      import asyncio
      return asyncio.run_coroutine_threadsafe(_default_and_callback(), self._loop)

"""
Start a conversation with an existing ElevenLabs Agent (voice or text-only).

Usage (voice, public agent):
  AGENT_ID=youragentid /Users/alexlatorre/Downloads/kg_biology_nasa/.venv/bin/python ElevenLabs/start_agent.py

Usage (voice, private agent with auth):
  AGENT_ID=youragentid ELEVENLABS_API_KEY=yourapikey /Users/alexlatorre/Downloads/kg_biology_nasa/.venv/bin/python ElevenLabs/start_agent.py

Text-only mode (no mic permission required):
  TEXT_ONLY=1 AGENT_ID=youragentid /Users/alexlatorre/Downloads/kg_biology_nasa/.venv/bin/python ElevenLabs/start_agent.py

Environment variables:
  - AGENT_ID (required): your agent id from ElevenLabs dashboard
  - ELEVENLABS_API_KEY (optional): required if your agent requires auth
  - USER_ID (optional): pass your app's end-user id for analytics
  - TEXT_ONLY (optional): set to '1' to run without audio
"""


def start_agent(agent_id: str, api_key: Optional[str] = None, user_id: Optional[str] = None, text_only: bool = False, initial_message: Optional[str] = None, tool_id: Optional[str] = None, tool_name: Optional[str] = None):
  elevenlabs = ElevenLabs(api_key=api_key)

  # Decide audio interface
  audio_interface: object
  if text_only:
    audio_interface = NullAudioInterface()
  else:
    # Try to use PyAudio first, then fall back to sounddevice, then text-only
    try:
      audio_interface = DefaultAudioInterface()  # type: ignore
      print("[voice] Voice mode enabled (PyAudio). Mic is live. Press Ctrl+C to end.")
    except Exception as e1:
      try:
        audio_interface = SDIAudioInterface()
        print("[voice] Voice mode enabled (sounddevice). Mic is live. Press Ctrl+C to end.")
      except Exception as e2:
        print(f"[info] Could not initialize audio (PyAudio error: {e1}; sounddevice error: {e2}). Falling back to TEXT-ONLY mode.")
        text_only = True
        audio_interface = NullAudioInterface()

  # Prepare client tools: register a passthrough for provided tool id (optional)
  client_tools = PrintingClientTools()
  # Simple, safe string result for tools (some agents expect plain text)
  def _string_tool_handler(params: dict, label: str):
    par = {k: v for k, v in params.items() if k != "tool_call_id"}
    # Summarize key-value pairs
    kv = ", ".join(f"{k}={v}" for k, v in par.items()) if par else "no-params"
    return f"{label} executed ({kv})"

  if tool_id:
    try:
      client_tools.register(tool_id, lambda p: _string_tool_handler(p, f"tool:{tool_id}"), is_async=False)
    except Exception:
      pass

  # Register the additional tool
  try:
    client_tools.register("tool_7701k6rg9ygreykr1apjnkxzm6eg", lambda p: _string_tool_handler(p, "tool:tool_7701k6rg9ygreykr1apjnkxzm6eg"), is_async=False)
  except Exception:
    pass

  # Register by tool name as well (platform sends tool_name in events)
  # If not provided, also register a common example name seen in events: 'open_cluster'
  effective_tool_name = tool_name or os.getenv("TOOL_NAME") or "open_cluster"
  try:
    client_tools.register(effective_tool_name, lambda p: _string_tool_handler(p, f"tool:{effective_tool_name}"), is_async=False)
  except Exception:
    pass

  # Register open_paper as well
  try:
    client_tools.register("open_paper", lambda p: _string_tool_handler(p, "tool:open_paper"), is_async=False)
  except Exception:
    pass

  conversation = Conversation(
    elevenlabs,
    agent_id,
    requires_auth=bool(api_key),
    audio_interface=audio_interface,
    client_tools=client_tools,
    callback_agent_response=lambda response: (print(f"Agent: {response}") or log_event_safe({"ts": iso_now(), "type": "agent", "text": str(response)})),
    callback_agent_response_correction=lambda original, corrected: print(f"Agent: {original} -> {corrected}"),
    callback_user_transcript=lambda transcript: (print(f"User: {transcript}") or log_event_safe({"ts": iso_now(), "type": "user", "text": str(transcript)})),
    # Uncomment to see latency measurements
    # callback_latency_measurement=lambda latency: print(f"Latency: {latency}ms"),
  )

  # Start session (no args in current SDK)
  # Reset active log for a clean stream (avoid stale events from prior runs)
  if LOG_CONV:
    try:
      os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
      with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("")
    except Exception:
      pass
  conversation.start_session()
  try:
    log_event({"ts": iso_now(), "type": "meta", "event": "session_started"})
  except Exception:
    pass

  # Graceful shutdown on Ctrl+C
  signal.signal(signal.SIGINT, lambda sig, frame: conversation.end_session())

  # If an initial message is provided in text-only mode, send it and wait briefly
  if text_only and initial_message:
    try:
      # allow websocket to establish before first message
      time.sleep(1.5)
      conversation.send_user_message(initial_message)
      # wait for agent response to arrive through callback
      time.sleep(5)
    except Exception as e:
      print(f"[error] initial send_user_message failed: {e}")
    finally:
      conversation.end_session()

  # In text-only mode without initial message, provide a simple input loop to send messages
  elif text_only:
    print("[text-only] Type messages for the agent. Use 'exit' to end.")
    try:
      while True:
        msg = input("> ").strip()
        if msg.lower() in ("exit", "quit", "/exit", ":q"):
          break
        if not msg:
          continue
        try:
          conversation.send_user_message(msg)
        except Exception as e:
          print(f"[error] send_user_message failed: {e}")
    except KeyboardInterrupt:
      pass
    finally:
      conversation.end_session()

  conversation_id = conversation.wait_for_session_end()
  print(f"Conversation ID: {conversation_id}")
  try:
    log_event({"ts": iso_now(), "type": "meta", "event": "conversation_end", "conversation_id": str(conversation_id)})
  except Exception:
    pass

  # Optionally pull conversation details from API to surface platform tool events
  if os.getenv("PRINT_TOOL_EVENTS") == "1" and api_key and conversation_id:
    try:
      details = elevenlabs.conversational_ai.conversations.get(conversation_id=conversation_id)
      # Best-effort scan for tool-related events
      events = []
      if isinstance(details, dict):
        events = details.get("events") or []
      elif hasattr(details, "events"):
        events = getattr(details, "events", [])
      printed = 0
      for ev in events or []:
        t = ev.get("type") if isinstance(ev, dict) else None
        if not t:
          continue
        if "tool" in t.lower():
          print(f"[platform] {t}: {ev}")
          printed += 1
      if printed == 0:
        print("[platform] No explicit tool events found in conversation details.")
    except Exception as e:
      print(f"[platform] Could not fetch conversation details for tool events: {e}")


if __name__ == "__main__":
  import argparse

  agent_id = os.getenv("AGENT_ID")
  api_key = os.getenv("ELEVENLABS_API_KEY")
  user_id = os.getenv("USER_ID")
  text_only_env = os.getenv("TEXT_ONLY") == "1"

  parser = argparse.ArgumentParser(description="Start a conversation with an ElevenLabs Agent")
  parser.add_argument("--message", dest="message", default=None, help="Send a single text message (text-only) and exit")
  parser.add_argument("--text-only", dest="text_only_cli", action="store_true", help="Force text-only mode (no audio)")
  parser.add_argument("--tool-id", dest="tool_id", default=os.getenv("TOOL_ID"), help="Optional: register a client tool by id and print its outputs")
  parser.add_argument("--tool-name", dest="tool_name", default=os.getenv("TOOL_NAME"), help="Optional: register a client tool by name (e.g., 'open_cluster')")
  parser.add_argument("--print-tool-events", dest="print_tool_events", action="store_true", help="After session ends, fetch conversation details (requires ELEVENLABS_API_KEY) and print platform tool events")
  args = parser.parse_args()

  if not agent_id:
    raise SystemExit("Please set AGENT_ID environment variable with your ElevenLabs Agent ID")

  text_only = text_only_env or args.text_only_cli

  if args.print_tool_events:
    os.environ["PRINT_TOOL_EVENTS"] = "1"

  start_agent(agent_id, api_key=api_key, user_id=user_id, text_only=text_only, initial_message=args.message, tool_id=args.tool_id, tool_name=args.tool_name)
