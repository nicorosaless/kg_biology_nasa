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

export const GraphDashboard = () => {
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [viewState, setViewState] = useState<ViewState>({ level: "universe" });
  const [searchQuery, setSearchQuery] = useState("");
  const [filters, setFilters] = useState({
    yearRange: [2000, 2025] as [number, number],
    missions: ["ISS", "Mars", "Moon"] as Mission[],
    showGaps: false,
  });
  const [scientistOpen, setScientistOpen] = useState(true);
  const [pendingFocusClusterId, setPendingFocusClusterId] = useState<string | null>(null);
  const [pendingPaperId, setPendingPaperId] = useState<string | null>(null); // drives GraphView animation
  const [queuedPaperId, setQueuedPaperId] = useState<string | null>(null); // waiting for cluster animation
  const [lastClusterRequestedId, setLastClusterRequestedId] = useState<string | null>(null);
  const [delayedOpenTimer, setDelayedOpenTimer] = useState<number | null>(null);

  // Helper to clear any outstanding delay timers
  const clearDelayTimer = () => {
    if (delayedOpenTimer) {
      window.clearTimeout(delayedOpenTimer);
      setDelayedOpenTimer(null);
    }
  };

  // When we enter topic view, clear queued/pending paper IDs to avoid replays
  useEffect(() => {
    if (viewState.level === "topic") {
      clearDelayTimer();
      setQueuedPaperId(null);
      setPendingPaperId(null);
    }
  }, [viewState.level]);
  // Voice is driven by SSE from backend; no direct client session here.

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

  // --- Deterministic resolvers for clusters and papers ---
  const normalize = (s: string) =>
    s
      .toLowerCase()
      .replace(/^\s*macrocluster\s*:\s*/, "")
      .replace(/[^a-z0-9\s]/g, " ")
      .replace(/\s+/g, " ")
      .trim();

  const jaccard = (a: string, b: string) => {
    const A = new Set(normalize(a).split(" ").filter(Boolean));
    const B = new Set(normalize(b).split(" ").filter(Boolean));
    if (A.size === 0 && B.size === 0) return 1;
    let inter = 0;
    A.forEach((t) => {
      if (B.has(t)) inter += 1;
    });
    const union = A.size + B.size - inter;
    return union === 0 ? 0 : inter / union;
  };

  const resolveClusterId = (params: Record<string, any>): string | null => {
    if (!graphData) return null;
    const candidates: string[] = [
      params.clusterId,
      params.id,
      params.cluster,
      params.cluster_name,
      params.name,
      params.label,
      params.topic,
    ].filter(Boolean) as string[];
    if (candidates.length === 0) return null;
    const query = candidates[0];
    const nq = normalize(String(query));

    // 1) Exact id match
    const byId = graphData.clusters.find((c) => c.id.toLowerCase() === String(query).toLowerCase());
    if (byId) return byId.id;

    // 2) Exact normalized label match
    const exact = graphData.clusters.find((c) => normalize(c.label) === nq);
    if (exact) return exact.id;

    // 3) StartsWith match on normalized label
    const starts = graphData.clusters.find((c) => normalize(c.label).startsWith(nq));
    if (starts) return starts.id;

    // 4) Best Jaccard similarity above threshold
    let bestId: string | null = null;
    let best = 0;
    for (const c of graphData.clusters) {
      const score = jaccard(c.label, nq);
      if (score > best) {
        best = score;
        bestId = c.id;
      }
    }
    return best >= 0.5 ? bestId : null;
  };

  const resolvePaperId = (params: Record<string, any>): string | null => {
    if (!graphData) return null;
    const candidates: string[] = [
      params.paperId,
      params.paper_id,
      params.id,
      params.pmid,
      params.doi,
      params.title,
      params.label,
    ].filter(Boolean) as string[];
    if (candidates.length === 0) return null;
    const query = candidates[0];
    const nq = normalize(String(query));

    // 1) Exact id match (paper.id)
    const byId = graphData.papers.find((p) => p.id.toLowerCase() === String(query).toLowerCase());
    if (byId) return byId.id;

    // 2) Exact normalized label (title)
    const exact = graphData.papers.find((p) => normalize(p.label) === nq);
    if (exact) return exact.id;

    // 3) StartsWith on normalized title
    const starts = graphData.papers.find((p) => normalize(p.label).startsWith(nq));
    if (starts) return starts.id;

    // 4) Best Jaccard similarity above threshold
    let bestId: string | null = null;
    let best = 0;
    for (const p of graphData.papers) {
      const score = jaccard(p.label, nq);
      if (score > best) {
        best = score;
        bestId = p.id;
      }
    }
    return best >= 0.6 ? bestId : null; // a bit stricter for papers
  };

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
              requestFocusClusterId={pendingFocusClusterId}
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
              requestOpenPaperId={pendingPaperId}
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
        onToggleVoice={() => { /* handled internally by sidebar SSE */ }}
        onToolEvent={(evt) => {
          if (!graphData) return;
          const name = evt.name;
          const p = evt.parameters || {};
          switch (name) {
            case "open_cluster": {
              const cid = resolveClusterId(p);
              if (cid) {
                // If we're in universe view, animate focus; otherwise, just navigate
                if (viewState.level === "universe") {
                  setPendingFocusClusterId(cid);
                  // Clear the request after a short delay to avoid re-triggering
                  setTimeout(() => setPendingFocusClusterId(null), 1600);
                } else {
                  handleClusterClick(cid);
                }
                // Remember cluster; open a queued paper (if any) after a deliberate delay (6s)
                setLastClusterRequestedId(cid);
                clearDelayTimer();
                const timer = window.setTimeout(() => {
                  // Only open if we have a queued paper and we're in the target cluster view
                  if (queuedPaperId) {
                    const targetPaper = graphData.papers.find((pp: Paper) => pp.id === queuedPaperId);
                    if (targetPaper && targetPaper.clusterId === cid) {
                      setPendingPaperId(queuedPaperId);
                    }
                  }
                }, 6000);
                setDelayedOpenTimer(timer);
              }
              break;
            }
            case "open_paper": {
              const pid = resolvePaperId(p);
              if (pid) {
                // Decide whether to queue for delayed open depending on current/last cluster selection
                const paper = graphData.papers.find((pp: Paper) => pp.id === pid);
                const paperClusterId = paper?.clusterId;

                // If a cluster open was just requested to this paper's cluster, queue and let the timer open it
                if (paperClusterId && lastClusterRequestedId === paperClusterId) {
                  setQueuedPaperId(pid);
                  // Timer created in open_cluster will handle opening in ~6s
                  break;
                }

                // If we're already in the paper's cluster view, open after a short cinematic delay (~1s)
                if (viewState.level === "cluster" && paperClusterId === viewState.selectedClusterId) {
                  clearDelayTimer();
                  const timer = window.setTimeout(() => setPendingPaperId(pid), 1000);
                  setDelayedOpenTimer(timer);
                  break;
                }

                // Otherwise, navigate to the paper's cluster first with animation, then open after delay
                if (paperClusterId) {
                  // Trigger universe -> cluster animation if needed
                  if (viewState.level === "universe") {
                    setPendingFocusClusterId(paperClusterId);
                    setTimeout(() => setPendingFocusClusterId(null), 1600);
                  } else {
                    handleClusterClick(paperClusterId);
                  }
                  setLastClusterRequestedId(paperClusterId);
                  setQueuedPaperId(pid);
                  clearDelayTimer();
                  const timer = window.setTimeout(() => setPendingPaperId(pid), 6000);
                  setDelayedOpenTimer(timer);
                }
              }
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
        }}
      />

  {/* ElevenLabs widget removed; integration will be programmatic. */}
    </div>
  );
};
