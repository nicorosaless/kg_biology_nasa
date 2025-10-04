import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "./ui/button";
import { Mic, MicOff, X, MessageCircle, Bot, User } from "lucide-react";

interface ScientistSidebarProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleVoice?: (active: boolean) => void;
}

export const ScientistSidebar = ({ open, onOpenChange, onToggleVoice }: ScientistSidebarProps) => {
  const [voiceActive, setVoiceActive] = useState(false);
  const [messages, setMessages] = useState<Array<{ role: "bot" | "user"; text: string }>>([
    { role: "bot", text: "Hello! I'm your designed scientist. Ask me about clusters, topics, or papers." },
  ]);

  const handleTalkClick = () => {
    const next = !voiceActive;
    setVoiceActive(next);
    onToggleVoice?.(next);
    if (next) {
      setMessages((prev) => [
        ...prev,
        { role: "bot", text: "[ElevenLabs] Voice agent is now active. I can guide you through the app." },
      ]);
    } else {
      setMessages((prev) => [
        ...prev,
        { role: "bot", text: "Voice agent stopped. Tap Talk to Scientist to resume." },
      ]);
    }
  };

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
                    alt="Albert Einstein"
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
