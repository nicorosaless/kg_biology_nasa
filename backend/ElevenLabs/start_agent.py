import os
import signal
import time
from typing import Optional

from elevenlabs.client import ElevenLabs
from elevenlabs.conversational_ai.conversation import Conversation
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
    self.output_queue: queue.Queue[bytes] = queue.Queue()
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
          # Convert raw PCM16 bytes to numpy int16 array for sounddevice
          if isinstance(audio, (bytes, bytearray)):
            np_audio = np.frombuffer(audio, dtype=np.int16)
          else:
            np_audio = audio
          self.out_stream.write(np_audio)
        except queue.Empty:
          pass
    self.thread = self.threading.Thread(target=output_thread, daemon=True)
    self.thread.start()

  def stop(self):
    self.should_stop.set()
    try:
      self.thread.join(timeout=1.0)
    except Exception:
      pass
    try:
      self.in_stream.stop(); self.in_stream.close()
      self.out_stream.stop(); self.out_stream.close()
    except Exception:
      pass

  def output(self, audio: bytes):
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


def start_agent(agent_id: str, api_key: Optional[str] = None, user_id: Optional[str] = None, text_only: bool = False, initial_message: Optional[str] = None):
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

  conversation = Conversation(
    elevenlabs,
    agent_id,
    requires_auth=bool(api_key),
    audio_interface=audio_interface,
    callback_agent_response=lambda response: print(f"Agent: {response}"),
    callback_agent_response_correction=lambda original, corrected: print(f"Agent: {original} -> {corrected}"),
    callback_user_transcript=lambda transcript: print(f"User: {transcript}"),
    # Uncomment to see latency measurements
    # callback_latency_measurement=lambda latency: print(f"Latency: {latency}ms"),
  )

  # Start session (no args in current SDK)
  conversation.start_session()

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


if __name__ == "__main__":
  import argparse

  agent_id = os.getenv("AGENT_ID")
  api_key = os.getenv("ELEVENLABS_API_KEY")
  user_id = os.getenv("USER_ID")
  text_only_env = os.getenv("TEXT_ONLY") == "1"

  parser = argparse.ArgumentParser(description="Start a conversation with an ElevenLabs Agent")
  parser.add_argument("--message", dest="message", default=None, help="Send a single text message (text-only) and exit")
  parser.add_argument("--text-only", dest="text_only_cli", action="store_true", help="Force text-only mode (no audio)")
  args = parser.parse_args()

  if not agent_id:
    raise SystemExit("Please set AGENT_ID environment variable with your ElevenLabs Agent ID")

  text_only = text_only_env or args.text_only_cli

  start_agent(agent_id, api_key=api_key, user_id=user_id, text_only=text_only, initial_message=args.message)
