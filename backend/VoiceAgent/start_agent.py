import os
import signal
import time
from typing import Optional
import json
from datetime import datetime
import threading
import errno
import re

# Lightweight JSONL logger so the frontend can stream conversation logs if desired.
LOG_CONV = os.getenv("LOG_CONVERSATION") == "1"
LOG_PATH = os.getenv("LOG_PATH") or os.path.join(os.path.dirname(__file__), "logs", "active.jsonl")

# Timing constants (seconds)
CLUSTER_DELAY_S = float(os.getenv("CLUSTER_DELAY_S", "5.0"))
PAPER_AFTER_PART2_DELAY_S = float(os.getenv("PAPER_AFTER_PART2_DELAY_S", "8.0"))

def _is_closing_prompt(text: str) -> bool:
  try:
    t = (text or "").strip().lower()
    if not t:
      return False
    closers = [
      "is there anything else i can help",
      "anything else i can help",
      "how else can i help",
      "what would you like to do next",
      "would you like to explore",
      "do you want to explore",
      "what else can i do",
      "let me know if you want",
      "are you still there",
      "are you still here",
      "do you have any other questions",
      "anything else you'd like",
      "anything else you want",
      "any other topic",
      "what else can i help",
    ]
    return any(phrase in t for phrase in closers)
  except Exception:
    return False

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

def _log_agent_text_with_deferral(client_tools: "PrintingClientTools", text: str):
  # If this looks like a closing prompt and UI is still busy, delay logging until after busy window
  try:
    if _is_closing_prompt(text):
      nowm = time.monotonic()
      with client_tools.queue_lock:
        release_at = max(client_tools.busy_until_ts, nowm)
      if release_at > nowm + 0.01:
        def worker(msg: str, at_ts: float):
          dt = max(0.0, at_ts - time.monotonic())
          if dt > 0:
            time.sleep(dt)
          try:
            print(f"Agent: {msg}")
            log_event_safe({"ts": iso_now(), "type": "agent", "text": msg})
          except Exception:
            pass
        threading.Thread(target=worker, args=(text, release_at), daemon=True).start()
        return
  except Exception:
    pass
  print(f"Agent: {text}")
  log_event_safe({"ts": iso_now(), "type": "agent", "text": text})

# Heuristic splitter: divide a long agent response into two coherent parts so we can
# interleave UI actions (open_cluster, then open_paper) with narration.
def _split_text_for_tools(text: str):
  try:
    t = str(text or "")
    # Prefer splitting at common cue phrases if present
    cues = [
      "Here’s a paper",
      "Here's a paper",
      "Here is a paper",
      "Here’s another",
      "Here's another",
      "Here is another",
      "Here’s one",
      "Here's one",
      "Here is one",
      "Next,",
      "Now,",
    ]
    for cue in cues:
      idx = t.find(cue)
      if idx > 40:  # ensure we keep a meaningful intro before the cue
        return t[:idx].strip(), t[idx:].strip()

    # Otherwise, split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', t)
    if len(sentences) >= 2:
      part1 = sentences[0]
      rest = sentences[1:]
      # If first sentence is too short, take two sentences for a smoother first part
      if len(part1) < 60 and len(rest) >= 1:
        part1 = (sentences[0] + " " + sentences[1]).strip()
        part2 = " ".join(sentences[2:]).strip() if len(sentences) > 2 else ""
      else:
        part2 = " ".join(rest).strip()
      if part1 and part2:
        return part1, part2
  except Exception:
    pass
  return None

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

# Output-only audio interface: play agent audio to speakers, don't capture mic
class OutputOnlyAudioInterface:
  OUTPUT_FRAMES_PER_BUFFER = 1000  # 62.5ms @ 16kHz

  def __init__(self):
    import sounddevice as sd  # type: ignore
    import queue, threading
    self.sd = sd
    self.queue = queue
    self.threading = threading
    self.output_queue: queue.Queue[object] = queue.Queue()
    self.should_stop = threading.Event()
    # Optional output device selection by name or index via env var
    self.device = os.getenv("SOUNDDEVICE_OUTPUT_DEVICE")
    # Optional: use macOS 'afplay' fallback instead of a stream
    self.use_afplay = os.getenv("AFPLAY_FALLBACK") == "1"

  def start(self, input_callback=None):
    # Ignore input; only handle output audio
    if not self.use_afplay:
      try:
        kwargs = dict(channels=1, samplerate=16000, dtype='int16', blocksize=self.OUTPUT_FRAMES_PER_BUFFER)
        if self.device:
          # Try parsing as int index, else pass string name
          try:
            kwargs["device"] = int(self.device)
          except Exception:
            kwargs["device"] = self.device
        self.out_stream = self.sd.OutputStream(**kwargs)
        self.out_stream.start()
      except Exception as e:
        print(f"[audio] Failed to open output stream ({e}). Falling back to 'afplay' if available. Devices:")
        try:
          print(self.sd.query_devices())
        except Exception:
          pass
        self.use_afplay = True

    def output_thread():
      import numpy as np
      import queue
      import subprocess, tempfile, wave, os as _os
      while not self.should_stop.is_set():
        try:
          audio = self.output_queue.get(timeout=0.25)
        except queue.Empty:
          continue
        if audio is None:
          break
        try:
          if self.use_afplay:
            # Write audio chunk to temp wav and play with afplay (macOS)
            raw = audio if isinstance(audio, (bytes, bytearray)) else bytes(audio)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
              name = tmp.name
            try:
              with wave.open(name, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # int16
                wf.setframerate(16000)
                wf.writeframes(raw)
              subprocess.run(["afplay", "-q", "1", name], check=False)
            finally:
              try:
                _os.remove(name)
              except Exception:
                pass
          else:
            if isinstance(audio, (bytes, bytearray)):
              np_audio = np.frombuffer(audio, dtype=np.int16)
            else:
              np_audio = audio
            self.out_stream.write(np_audio)
        except Exception:
          break
    self.thread = self.threading.Thread(target=output_thread, daemon=True)
    self.thread.start()

  def stop(self):
    self.should_stop.set()
    try:
      try:
        self.output_queue.put_nowait(None)
      except Exception:
        pass
      self.thread.join(timeout=1.0)
    except Exception:
      pass
    if not self.use_afplay:
      try:
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
    self.pending_tool_events = []
    self.agent_has_spoken = threading.Event()
    self.queue_lock = threading.Lock()
    # If agent speaks before tools arrive, store desired release delays to apply on next tool arrivals
    self.deferred_delays: list[float] = []
    # Absolute scheduling tied to speech start
    self.speech_start_at: Optional[float] = None
    self.desired_release_times: list[float] = []  # absolute times (monotonic) when next arriving tool should release
    self.busy_until_ts: float = 0.0  # guard for closing prompts

  def _enqueue_tool_event(self, ev: dict):
    with self.queue_lock:
      # Prioritize cluster openings before paper openings to match desired flow
      tool = str(ev.get("tool") or "").lower()
      if tool == "open_cluster":
        self.pending_tool_events.insert(0, ev)
      else:
        self.pending_tool_events.append(ev)
      # If agent already spoke and we have an absolute desired release time, schedule this event accordingly
      if self.agent_has_spoken.is_set() and self.desired_release_times:
        desired_ts = self.desired_release_times.pop(0)
        now = time.monotonic()
        delay_s = max(0.0, desired_ts - now)
        try:
          self._try_release_specific_event(ev, delay_s=delay_s)
          return
        except Exception:
          pass

  def _try_release_specific_event(self, ev: dict, delay_s: float = 0.0):
    def worker():
      if delay_s > 0:
        time.sleep(delay_s)
      removed = None
      with self.queue_lock:
        # If still pending, remove and log
        try:
          idx = self.pending_tool_events.index(ev)
        except ValueError:
          idx = -1
        if idx >= 0:
          removed = self.pending_tool_events.pop(idx)
      if removed is not None:
        try:
          log_event(removed)
        except Exception:
          pass
    threading.Thread(target=worker, daemon=True).start()

  def release_one_pending_tool(self, delay_s: float = 0.5):
    """Release (log) exactly one pending tool event after a small delay.
    This is called after each agent utterance so UI actions line up with speech.
    """
    ev = None
    with self.queue_lock:
      if self.pending_tool_events:
        ev = self.pending_tool_events.pop(0)
    if ev is not None:
      # Small UX delay so the UI action follows the spoken cue naturally
      self._try_release_specific_event(ev, delay_s=delay_s)

  def note_desired_release(self, delay_s: float):
    """Queue a desired release timing to apply to the next arriving tool event."""
    with self.queue_lock:
      self.deferred_delays.append(delay_s)

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
      
      # Create the tool event
      tool_event = {
        "ts": iso_now(),
        "type": "tool",
        "tool": tool_name,
        # Log the original parameters provided to the tool call (excluding tool_call_id)
        "parameters": {k: v for k, v in (parameters or {}).items() if k != "tool_call_id"},
        "result": text,
      }
      
      # Queue the tool event; do not log immediately.
      # It will be released right after the next agent utterance so the UI matches speech.
      self._enqueue_tool_event(tool_event)
      
      # Fallback: if no agent utterance arrives soon, release this tool automatically
      def fallback_release():
        # Wait up to ~15 seconds; if still pending, release to avoid a stuck UI.
        self.agent_has_spoken.wait(timeout=15)
        # Regardless of speech, ensure this tool isn't stuck forever.
        self._try_release_specific_event(tool_event, delay_s=0.0)
      threading.Thread(target=fallback_release, daemon=True).start()
      
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
    # Prefer output-only mode if requested, then PyAudio, then sounddevice, then text-only
    if os.getenv("OUTPUT_ONLY") == "1":
      try:
        audio_interface = OutputOnlyAudioInterface()
        print("[voice] Output-only mode enabled. Speak in the browser; agent audio plays locally.")
      except Exception as e:
        print(f"[info] OutputOnlyAudioInterface failed: {e}. Falling back to default audio.")
        audio_interface = None
    else:
      audio_interface = None

    if audio_interface is None:
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
    client_tools.register("tool_5301k6sz71gpetda5xqrxah3mpqe", lambda p: _string_tool_handler(p, "tool:tool_2301k6sz6bfbf6ztzn2fkbxds45z"), is_async=False)
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

  # Create callback that signals when agent starts speaking
  def agent_response_callback(response):
    # Signal that agent has started speaking
    client_tools.agent_has_spoken.set()
    if client_tools.speech_start_at is None:
      try:
        client_tools.speech_start_at = time.monotonic()
      except Exception:
        client_tools.speech_start_at = 0.0
    text = str(response)
    # If we have pending tool events, try to split response in two parts
    has_pending = False
    try:
      with client_tools.queue_lock:
        has_pending = len(client_tools.pending_tool_events) > 0
    except Exception:
      pass

    if has_pending:
      split = _split_text_for_tools(text)
      if split:
        part1, part2 = split
        if part1:
          _log_agent_text_with_deferral(client_tools, part1)
        # Schedule first tool ~5s after this first narration part
        with client_tools.queue_lock:
          first_at = time.monotonic() + CLUSTER_DELAY_S
          if client_tools.pending_tool_events:
            ev = client_tools.pending_tool_events.pop(0)
            now = time.monotonic()
            client_tools._try_release_specific_event(ev, delay_s=max(0.0, first_at - now))
            try:
              log_event_safe({"ts": iso_now(), "type": "meta", "event": "schedule_tool", "which": "first", "at_s": first_at})
            except Exception:
              pass
          # mark UI busy until after first action lands
          try:
            client_tools.busy_until_ts = max(client_tools.busy_until_ts, first_at + 0.5)
          except Exception:
            pass
          else:
            client_tools.desired_release_times.append(first_at)
            try:
              log_event_safe({"ts": iso_now(), "type": "meta", "event": "schedule_tool_future", "which": "first", "at_s": first_at})
            except Exception:
              pass
        if part2:
          # Brief pause before the second narration part
          time.sleep(1.5)
          _log_agent_text_with_deferral(client_tools, part2)
          # Schedule second tool ~8s after part2
          with client_tools.queue_lock:
            second_at = time.monotonic() + PAPER_AFTER_PART2_DELAY_S
            if client_tools.pending_tool_events:
              ev2 = client_tools.pending_tool_events.pop(0)
              now = time.monotonic()
              client_tools._try_release_specific_event(ev2, delay_s=max(0.0, second_at - now))
              try:
                log_event_safe({"ts": iso_now(), "type": "meta", "event": "schedule_tool", "which": "second", "at_s": second_at})
              except Exception:
                pass
            # mark UI busy until after second action lands
            try:
              client_tools.busy_until_ts = max(client_tools.busy_until_ts, second_at + 0.5)
            except Exception:
              pass
            else:
              client_tools.desired_release_times.append(second_at)
              try:
                log_event_safe({"ts": iso_now(), "type": "meta", "event": "schedule_tool_future", "which": "second", "at_s": second_at})
              except Exception:
                pass
        return

    # Fallback: no split or no pending tools — behave as before, but delay closing prompts if UI still busy
    try:
      if _is_closing_prompt(text):
        nowm = time.monotonic()
        with client_tools.queue_lock:
          release_at = max(client_tools.busy_until_ts, nowm)
        if release_at > nowm + 0.01:
          def _delay_log_closer(msg: str, at_ts: float):
            def worker():
              dt = max(0.0, at_ts - time.monotonic())
              if dt > 0:
                time.sleep(dt)
              try:
                print(f"Agent: {msg}")
                log_event_safe({"ts": iso_now(), "type": "agent", "text": msg})
              except Exception:
                pass
            threading.Thread(target=worker, daemon=True).start()
          _delay_log_closer(text, release_at)
          return
    except Exception:
      pass
    _log_agent_text_with_deferral(client_tools, text)
    # Single-part fallback: schedule using fixed delays from now
    with client_tools.queue_lock:
      base = time.monotonic()
      targets = [base + CLUSTER_DELAY_S, base + CLUSTER_DELAY_S + PAPER_AFTER_PART2_DELAY_S]
      # First, schedule for any currently pending events
      qlen = len(client_tools.pending_tool_events)
      for t in targets[:qlen]:
        if client_tools.pending_tool_events:
          ev = client_tools.pending_tool_events.pop(0)
          now = time.monotonic()
          client_tools._try_release_specific_event(ev, delay_s=max(0.0, t - now))
          try:
            log_event_safe({"ts": iso_now(), "type": "meta", "event": "schedule_tool", "which": "auto", "at_s": t})
          except Exception:
            pass
      # For any remaining targets with no pending events, store desired times for future arrivals
      if qlen < len(targets):
        for t in targets[qlen:]:
          client_tools.desired_release_times.append(t)
          try:
            log_event_safe({"ts": iso_now(), "type": "meta", "event": "schedule_tool_future", "which": "auto", "at_s": t})
          except Exception:
            pass

  conversation = Conversation(
    elevenlabs,
    agent_id,
    requires_auth=bool(api_key),
    audio_interface=audio_interface,
    client_tools=client_tools,
    callback_agent_response=agent_response_callback,
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

  # Optional: listen for user text messages from a named pipe (FIFO) and forward to the agent
  fifo_path = os.getenv("INBOX_FIFO")
  if fifo_path:
    try:
      # Create FIFO if it doesn't exist
      if not os.path.exists(fifo_path):
        os.mkfifo(fifo_path)

      def _fifo_reader():
        while True:
          try:
            with open(fifo_path, "r", encoding="utf-8") as fifo:
              for line in fifo:
                msg = line.strip()
                if not msg:
                  continue
                try:
                  log_event_safe({"ts": iso_now(), "type": "user", "text": msg})
                  conversation.send_user_message(msg)
                except Exception:
                  pass
          except FileNotFoundError:
            break
          except Exception as e:
            # Recreate FIFO if it was removed
            try:
              if not os.path.exists(fifo_path):
                os.mkfifo(fifo_path)
            except Exception:
              pass
            # brief backoff
            time.sleep(0.2)

      threading.Thread(target=_fifo_reader, daemon=True).start()
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
