import { useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "./ui/button";
import { Mic, MicOff, X, MessageCircle, Bot, User } from "lucide-react";
// We render live conversation by subscribing to the backend SSE stream produced by start_agent.py

interface ScientistSidebarProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleVoice?: (active: boolean) => void;
  onToolEvent?: (evt: { name: string; parameters?: Record<string, any>; result?: any }) => void;
}

export const ScientistSidebar = ({ open, onOpenChange, onToggleVoice, onToolEvent }: ScientistSidebarProps) => {
  const [voiceActive, setVoiceActive] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: "bot" | "user"; text: string }>>([]);
  const sseRef = useRef<EventSource | null>(null);
  const recogRef = useRef<any | null>(null);
  // Use this to ignore any SSE events that occurred before we started this session
  const dropBeforeTsRef = useRef<number | null>(null);
  // Track last messages to prevent duplicates in rapid succession
  const lastUserRef = useRef<{ text: string; t: number } | null>(null);
  const lastBotRef = useRef<{ text: string; t: number } | null>(null);

  const handleTalkClick = async () => {
    const next = !voiceActive;
    setVoiceActive(next);
    onToggleVoice?.(next);
    if (next) {
      // Start listening to live conversation logs via SSE
      try {
        // Ensure any previous agent/log stream is stopped, and start with a clean slate
        try {
          const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
          const stopUrl = backend ? `${backend}/api/conversation/stop` : "/api/conversation/stop";
          await fetch(stopUrl, { method: "POST" }).catch(() => {});
        } catch {}

        // Clear UI messages and record the time so we ignore any stale SSE events
        setMessages([]);
        dropBeforeTsRef.current = Date.now();

        // Request backend to start the agent fresh
        const agentId = (import.meta as any).env?.VITE_ELEVENLABS_AGENT_ID as string | undefined;
        if (agentId) {
          const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
          const startUrl = backend ? `${backend}/api/conversation/start` : "/api/conversation/start";
          await fetch(startUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            // Start with audio output enabled; user input comes from browser STT
            body: JSON.stringify({ agentId, textOnly: false }),
          }).catch(() => {});
        } else {
          setMessages((prev) => [...prev, { role: "bot", text: "VITE_ELEVENLABS_AGENT_ID is not set." }]);
        }
        const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
        const url = backend ? `${backend}/api/conversation/stream` : "/api/conversation/stream";
        // Small delay to give the backend time to rotate/reset logs
        await new Promise((r) => setTimeout(r, 250));
        const es = new EventSource(url);
        sseRef.current = es;
        es.onopen = () => {};
        es.onmessage = (evt) => {
          try {
            const data = JSON.parse(evt.data);
            // Ignore any stale events before we started this session
            const tsStr = (data && (data.ts || data.timestamp)) as string | undefined;
            if (tsStr && dropBeforeTsRef.current) {
              const ts = Date.parse(tsStr);
              if (!Number.isNaN(ts) && ts < dropBeforeTsRef.current - 500) {
                return;
              }
            }
            // Map log types to UI roles
            if (data?.type === "user" && data.text) {
              const text = String(data.text);
              const now = Date.now();
              const last = lastUserRef.current;
              if (!last || last.text !== text || now - last.t > 1500) {
                setMessages((prev) => [...prev, { role: "user", text }]);
                lastUserRef.current = { text, t: now };
              }
            } else if (data?.type === "agent" && data.text) {
              const text = String(data.text);
              const now = Date.now();
              const last = lastBotRef.current;
              if (!last || last.text !== text || now - last.t > 1500) {
                setMessages((prev) => [...prev, { role: "bot", text }]);
                lastBotRef.current = { text, t: now };
              }
            } else if (data?.type === "tool") {
              // Do not show tool events in the chat; only propagate for app reactions
              const label = data?.tool || "tool";
              onToolEvent?.({ name: String(label), parameters: data?.parameters, result: data?.result });
            } else if (data?.type === "meta") {
              // Hide meta events such as session_started to keep the chat clean
            }
          } catch (e) {
            // ignore malformed events
          }
        };
        es.onerror = () => {
          // Intentionally keep silent to avoid chat noise
        };

        // Start browser speech recognition to capture user's voice as text
        const SR: any = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
        if (SR) {
          const rec = new SR();
          rec.lang = "en-US";
          rec.continuous = true;
          rec.interimResults = false;
          rec.onresult = async (e: any) => {
            for (let i = e.resultIndex; i < e.results.length; i++) {
              const res = e.results[i];
              if (res.isFinal) {
                const transcript = res[0]?.transcript?.trim();
                if (transcript) {
                  try {
                    const sendUrl = backend ? `${backend}/api/conversation/send` : "/api/conversation/send";
                    await fetch(sendUrl, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({ text: transcript }),
                    });
                  } catch (err) {
                    // ignore
                  }
                }
              }
            }
          };
          rec.onerror = (err: any) => {
            // Optional: surface a hint if mic permission denied
            setMessages((prev) => [...prev, { role: "bot", text: "Mic/recognition error. Check permissions and try again." }]);
          };
          try { rec.start(); } catch {}
          recogRef.current = rec;
        } else {
          setMessages((prev) => [...prev, { role: "bot", text: "Speech recognition not supported in this browser. Type input not yet wired." }]);
        }
      } catch (e) {
        console.error("SSE connection failed", e);
        setVoiceActive(false);
        onToggleVoice?.(false);
      }
    } else {
      // Stop listening
      try {
        sseRef.current?.close();
        sseRef.current = null;
      } catch {}
      try {
        recogRef.current?.stop?.();
      } catch {}
      try {
        const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
        const stopUrl = backend ? `${backend}/api/conversation/stop` : "/api/conversation/stop";
        await fetch(stopUrl, { method: "POST" });
      } catch {}
    }
  };

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      try {
        sseRef.current?.close();
      } catch {}
      try {
        recogRef.current?.stop?.();
      } catch {}
      try {
        const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
        const stopUrl = backend ? `${backend}/api/conversation/stop` : "/api/conversation/stop";
        fetch(stopUrl, { method: "POST" }).catch(() => {});
      } catch {}
    };
  }, []);

  return (
    <>
      {/* Floating button when closed */}
      <AnimatePresence>
        {!open && (
          <motion.button
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            className="fixed bottom-6 right-6 w-14 h-14 rounded-full shadow-lg bg-gradient-to-br from-indigo-500 to-cyan-500 text-white flex items-center justify-center border border-white/20"
            onClick={() => onOpenChange(true)}
            aria-label="Open Scientist Sidebar"
          >
            <MessageCircle width={24} height={24} />
          </motion.button>
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <AnimatePresence>
        {open && (
          <motion.aside
            initial={{ x: 400, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 400, opacity: 0 }}
            transition={{ type: "spring", stiffness: 260, damping: 28 }}
            className="w-[20vw] min-w-[280px] max-w-[420px] h-screen fixed right-0 top-0 z-40 flex flex-col border-l border-border bg-background/70 backdrop-blur-xl"
          >
            {/* Header */}
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/20 via-fuchsia-500/20 to-cyan-500/20" />
              <div className="relative p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <img
                    src="/placeholder.svg"
                    alt="Scientist"
                    className="w-12 h-12 rounded-full ring-2 ring-white/40 shadow object-cover"
                  />
                  <div>
                    <div className="font-semibold leading-tight">Albert Einstein</div>
                    <div className="text-xs text-muted-foreground">
                      Your designed scientist at your disposal 24/7
                    </div>
                  </div>
                </div>
                <button
                  className="p-2 rounded-md hover:bg-white/10 text-muted-foreground"
                  onClick={() => onOpenChange(false)}
                  aria-label="Close Sidebar"
                >
                  <X size={18} />
                </button>
              </div>
              <div className="border-b border-border" />
            </div>

            {/* Controls */}
            <div className="p-4 border-b border-border flex items-center gap-2">
              <Button className="flex-1" variant={voiceActive ? "default" : "secondary"} onClick={handleTalkClick}>
                {voiceActive ? <Mic className="mr-2 h-4 w-4" /> : <MicOff className="mr-2 h-4 w-4" />}
                {voiceActive ? "Stop Talking" : "Talk to Scientist"}
              </Button>
            </div>

            {/* Chat area */}
            <div className="flex-1 overflow-auto p-4 space-y-3">
              {messages.map((m, i) => (
                <div key={i} className={`flex items-start gap-2 ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                  {m.role === "bot" && (
                    <div className="mt-0.5 text-muted-foreground"><Bot size={16} /></div>
                  )}
                  <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm shadow ${m.role === "user" ? "bg-primary text-primary-foreground" : "bg-card border border-border"}`}>
                    {m.text}
                  </div>
                  {m.role === "user" && (
                    <div className="mt-0.5 text-muted-foreground"><User size={16} /></div>
                  )}
                </div>
              ))}
            </div>
          </motion.aside>
        )}
      </AnimatePresence>
    </>
  );
};
