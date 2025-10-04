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
  const [messages, setMessages] = useState<Array<{ role: "bot" | "user"; text: string }>>([
    { role: "bot", text: "Hello! I'm your designed scientist. Ask me about clusters, topics, or papers." },
  ]);
  const sseRef = useRef<EventSource | null>(null);

  const handleTalkClick = async () => {
    const next = !voiceActive;
    setVoiceActive(next);
    onToggleVoice?.(next);
    if (next) {
      // Start listening to live conversation logs via SSE
      try {
        // Also request backend to start the agent if not running
        const agentId = (import.meta as any).env?.VITE_ELEVENLABS_AGENT_ID as string | undefined;
        if (agentId) {
          const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
          const startUrl = backend ? `${backend}/api/conversation/start` : "/api/conversation/start";
          await fetch(startUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ agentId, textOnly: true, message: "Session started from UI" }),
          }).catch(() => {});
        } else {
          setMessages((prev) => [...prev, { role: "bot", text: "VITE_ELEVENLABS_AGENT_ID is not set." }]);
        }
        const backend = (import.meta as any).env?.VITE_BACKEND_ORIGIN as string | undefined;
        const url = backend ? `${backend}/api/conversation/stream` : "/api/conversation/stream";
        const es = new EventSource(url);
        sseRef.current = es;
        es.onopen = () => {
          setMessages((prev) => [...prev, { role: "bot", text: "Listening for agent conversation…" }]);
        };
        es.onmessage = (evt) => {
          try {
            const data = JSON.parse(evt.data);
            // Map log types to UI roles
            if (data?.type === "user" && data.text) {
              setMessages((prev) => [...prev, { role: "user", text: String(data.text) }]);
            } else if (data?.type === "agent" && data.text) {
              setMessages((prev) => [...prev, { role: "bot", text: String(data.text) }]);
            } else if (data?.type === "tool") {
              const label = data?.tool || "tool";
              const p = data?.parameters ? `: ${JSON.stringify(data.parameters)}` : "";
              const res = data?.result ? ` => ${String(data.result)}` : "";
              setMessages((prev) => [...prev, { role: "bot", text: `[${label}]${p}${res}` }]);
              // Propagate tool event upward so the app can react (e.g., navigate graph)
              onToolEvent?.({ name: String(label), parameters: data?.parameters, result: data?.result });
            } else if (data?.type === "meta") {
              const ev = data?.event || "meta";
              const extra = data?.conversation_id ? ` (${data.conversation_id})` : "";
              setMessages((prev) => [...prev, { role: "bot", text: `[${ev}]${extra}` }]);
            }
          } catch (e) {
            // ignore malformed events
          }
        };
        es.onerror = () => {
          // Backend may not be logging yet or stream closed
          setMessages((prev) => [...prev, { role: "bot", text: "No live logs yet. Start the Python agent with LOG_CONVERSATION=1." }]);
        };
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
