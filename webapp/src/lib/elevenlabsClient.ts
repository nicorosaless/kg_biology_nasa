// Lightweight ElevenLabs voice client scaffold for programmatic control from the UI.
// This expects a backend endpoint to mint an ephemeral client token for the specified agent.
// Replace the TODOs with the actual ElevenLabs WebRTC/WebSocket connection code once available.

export type ToolEvent = {
  name: string;
  parameters?: Record<string, any>;
};

export interface VoiceSessionOptions {
  agentId: string;
  // Optional: if you already have a client token, pass it; otherwise we call your /api/elevenlabs/token endpoint
  token?: string;
  // Called when the agent invokes a client tool (function) like open_cluster, search, etc.
  onTool?: (evt: ToolEvent) => void;
  // Called when the agent emits a user-visible message (transcript or bot text)
  onMessage?: (role: "bot" | "user", text: string) => void;
}

export interface VoiceSessionHandle {
  stop: () => void;
}

async function fetchClientToken(agentId: string): Promise<string> {
  // This endpoint should be implemented on your server.
  // It should mint a short-lived client token using your server-side ELEVENLABS_API_KEY.
  const res = await fetch("/api/elevenlabs/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agentId }),
  });
  if (!res.ok) {
    throw new Error(`Failed to get ElevenLabs token: ${res.status}`);
  }
  const data = await res.json();
  if (!data?.token) throw new Error("Token missing in response");
  return data.token as string;
}

export async function startVoiceSession(opts: VoiceSessionOptions): Promise<VoiceSessionHandle> {
  const token = opts.token ?? (await fetchClientToken(opts.agentId));

  // TODO: Replace with real ElevenLabs WebRTC/WebSocket connection using the token.
  // For now, this scaffold simulates a connected session and wires browser microphone permissions.
  let stopped = false;
  let micStream: MediaStream | null = null;

  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (e) {
    console.error("Microphone permission denied:", e);
    opts.onMessage?.("bot", "I need microphone access to talk. Please allow mic permissions and try again.");
  }

  // Example: announce connected
  opts.onMessage?.("bot", "Voice link established. How can I help you navigate the research graph?");

  // Example: Simulate receiving a tool event from the agent after a short delay
  // Remove this once real events come from ElevenLabs SDK.
  const demoTimer = setTimeout(() => {
    if (!stopped) {
      opts.onTool?.({ name: "search", parameters: { query: "microgravity" } });
    }
  }, 3000);

  return {
    stop: () => {
      stopped = true;
      clearTimeout(demoTimer);
      micStream?.getTracks().forEach((t) => t.stop());
      opts.onMessage?.("bot", "Voice session ended.");
    },
  };
}
