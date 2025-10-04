import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { GraphData, ViewState, Mission, Cluster, Paper } from "../types/graph";
import { Toolbar } from "./Toolbar";
// import { Sidebar } from "./Sidebar";
import { ClusterView } from "./ClusterView";
import { GraphView } from "./GraphView";
import { TopicGraph } from "./TopicGraph";
import { PaperDetail } from "./PaperDetail";
import { ScientistSidebar } from "./ScientistSidebar";
import { startVoiceSession, ToolEvent } from "../lib/elevenlabsClient";

export const GraphDashboard = () => {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [viewState, setViewState] = useState<ViewState>({ level: "universe" });
  const [searchQuery, setSearchQuery] = useState("");
  const [filters, setFilters] = useState({
    yearRange: [2015, 2023] as [number, number],
    missions: ["ISS", "Mars", "Moon"] as Mission[],
    showGaps: false,
  });
  const [scientistOpen, setScientistOpen] = useState(true);
  const [voiceHandle, setVoiceHandle] = useState<{ stop: () => void } | null>(null);
  // ElevenLabs widget removed; future voice control will be triggered from the button.

  useEffect(() => {
    // Load mock data
    fetch("/data/csvGraph.json")
      .then((res) => res.json())
      .then((data) => setGraphData(data))
      .catch((err) => console.error("Failed to load graph data:", err));
  }, []);

  const handleClusterClick = (clusterId: string) => {
    setViewState({ level: "cluster", selectedClusterId: clusterId });
  };

  const handlePaperClick = (paperId: string) => {
    setViewState({ ...viewState, level: "topic", selectedPaperId: paperId });
  };

  const handleBackToUniverse = () => {
    setViewState({ level: "universe" });
  };

  const handleBackToCluster = () => {
    setViewState({ level: "cluster", selectedClusterId: viewState.selectedClusterId });
  };

  if (!graphData) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="text-center"
        >
          <div className="mb-4 h-12 w-12 animate-pulse-glow rounded-full bg-gradient-cosmic mx-auto" />
          <p className="text-foreground">Loading Knowledge Universe...</p>
        </motion.div>
      </div>
    );
  }

  const selectedCluster: Cluster | undefined = viewState.selectedClusterId
    ? graphData.clusters.find((c: Cluster) => c.id === viewState.selectedClusterId)
    : undefined;

  const selectedPaper: Paper | undefined = viewState.selectedPaperId
    ? graphData.papers.find((p: Paper) => p.id === viewState.selectedPaperId)
    : undefined;

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden">
      {/* Main Graph Area (expands when sidebar closed) */}
      <div className={`flex flex-col transition-all duration-300 ${scientistOpen ? "w-[80vw]" : "w-[100vw]"}`}>
        <Toolbar
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          filters={filters}
          onFiltersChange={setFilters}
          viewState={viewState}
          onBackToUniverse={handleBackToUniverse}
          onBackToCluster={handleBackToCluster}
          selectedClusterLabel={selectedCluster?.label}
          selectedPaperLabel={selectedPaper?.label}
        />

        <div className="flex-1 relative overflow-hidden">
          {/* Space-like background */}
          <div className="absolute inset-0 -z-10">
            <div className="absolute inset-0 bg-gradient-to-b from-black via-[#0b1020] to-[#05070f]" />
            {/* Stars */}
            <div className="pointer-events-none absolute inset-0 opacity-60" style={{ backgroundImage: "radial-gradient(2px 2px at 20% 30%, rgba(255,255,255,0.6), rgba(255,255,255,0) 40%), radial-gradient(1.5px 1.5px at 70% 60%, rgba(255,255,255,0.5), rgba(255,255,255,0) 40%), radial-gradient(1px 1px at 40% 80%, rgba(255,255,255,0.4), rgba(255,255,255,0) 40%)" }} />
            {/* Nebula clouds */}
            <div className="absolute -top-20 -left-20 w-[60vw] h-[60vw] bg-fuchsia-500/10 blur-[100px] rounded-full animate-pulse-glow" />
            <div className="absolute bottom-0 right-0 w-[50vw] h-[50vw] bg-cyan-500/10 blur-[100px] rounded-full animate-pulse-glow" />
          </div>
          {viewState.level === "universe" && (
            <ClusterView
              clusters={graphData.clusters}
              onClusterClick={handleClusterClick}
              filters={filters}
            />
          )}

          {viewState.level === "cluster" && selectedCluster && (
            <GraphView
              cluster={selectedCluster}
              papers={graphData.papers.filter((p: Paper) => p.clusterId === selectedCluster.id)}
              edges={graphData.edges}
              onPaperClick={handlePaperClick}
              filters={filters}
              searchQuery={searchQuery}
            />
          )}

          {viewState.level === "topic" && selectedPaper && (
            <PaperDetail paper={selectedPaper} />
          )}
        </div>
      </div>

      {/* Scientist Sidebar - toggleable */}
      <ScientistSidebar
        open={scientistOpen}
        onOpenChange={setScientistOpen}
        onToggleVoice={async (active) => {
          if (active) {
            try {
              const handle = await startVoiceSession({
                agentId: "agent_5501k6r63xjmf938t6gvsgqby1hh",
                onMessage: (role, text) => {
                  // Optionally pipe messages to sidebar UI via custom event or state (kept internal for now)
                  console.debug("[Voice]", role, text);
                },
                onTool: (evt: ToolEvent) => {
                  const name = evt.name;
                  const p = evt.parameters || {};
                  if (!graphData) return;
                  switch (name) {
                    case "open_cluster": {
                      const topic = String(p.topic || "").toLowerCase();
                      const c = graphData.clusters.find((c) => c.label.toLowerCase().includes(topic));
                      if (c) handleClusterClick(c.id);
                      break;
                    }
                    case "open_paper": {
                      const title = String(p.title || "").toLowerCase();
                      const match = graphData.papers.find((pp) => pp.label.toLowerCase().includes(title) || pp.id.toLowerCase() === title);
                      if (match) handlePaperClick(match.id);
                      break;
                    }
                    case "filter_mission": {
                      const mission = String(p.mission || "").toLowerCase();
                      const m: any = ["iss", "mars", "moon"].find((x) => x === mission);
                      if (m) setFilters((f) => ({ ...f, missions: [m.toUpperCase()] as any }));
                      break;
                    }
                    case "search": {
                      const query = String(p.query || "");
                      setSearchQuery(query);
                      break;
                    }
                    case "show_summary": {
                      // Could trigger a UI hint or ensure PaperDetail tab is Summary
                      break;
                    }
                    case "highlight_gaps": {
                      setFilters((f) => ({ ...f, showGaps: true }));
                      break;
                    }
                    case "compare_clusters": {
                      // Future: open a compare view
                      break;
                    }
                    case "idea_link": {
                      // Future: suggest related papers/topics
                      break;
                    }
                    case "back": {
                      if (viewState.level === "topic") handleBackToCluster();
                      else setViewState({ level: "universe" });
                      break;
                    }
                    default:
                      break;
                  }
                },
              });
              setVoiceHandle(handle);
            } catch (e) {
              console.error(e);
            }
          } else {
            voiceHandle?.stop();
            setVoiceHandle(null);
          }
        }}
      />

  {/* ElevenLabs widget removed; integration will be programmatic. */}
    </div>
  );
};
