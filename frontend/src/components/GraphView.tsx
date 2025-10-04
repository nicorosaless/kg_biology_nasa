import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import cytoscape from "cytoscape";
import { Cluster, Paper, Edge, Mission } from "../types/graph";

interface GraphViewProps {
  cluster: Cluster;
  papers: Paper[];
  edges: Edge[];
  onPaperClick: (paperId: string) => void;
  filters: {
    missions: Mission[];
    showGaps: boolean;
    yearRange: [number, number];
  };
  searchQuery: string;
  // Optional: request programmatic open of a paper node with animation
  requestOpenPaperId?: string | null;
}

export const GraphView = ({
  papers,
  edges,
  onPaperClick,
  filters,
  searchQuery,
  requestOpenPaperId,
}: GraphViewProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const onPaperClickRef = useRef(onPaperClick);
  const [overlayLabel, setOverlayLabel] = useState<string | null>(null);
  const [vignette, setVignette] = useState(false);
  const [hoverTip, setHoverTip] = useState<{ x: number; y: number; text: string } | null>(null);
  const [isLayingOut, setIsLayingOut] = useState(true);

  // keep latest handler without forcing effect re-runs
  useEffect(() => {
    onPaperClickRef.current = onPaperClick;
  }, [onPaperClick]);
  
  const STOPWORDS = new Set([
    "the","a","an","and","or","of","in","on","for","to","with","by","from","at","as","is","are","be","that","this","these","those","into","via","using","during","after","before","over","under","about","without","within","between"
  ]);
  const summarizeTitle = (title: string, maxLen = 28) => {
    // keep meaningful tokens: >3 chars, non-stopword, keep acronyms/numbers
    const tokens = title
      .replace(/[\"\.:;,()\[\]\-]/g, " ")
      .split(/\s+/)
      .filter(Boolean);
    const keep: string[] = [];
    for (const t of tokens) {
      const bare = t.trim();
      const lower = bare.toLowerCase();
      const isAcr = /^[A-Z0-9]{3,}$/.test(bare);
      if (isAcr || bare.length > 3) {
        if (!STOPWORDS.has(lower)) keep.push(bare);
      }
      if (keep.length >= 8) break;
    }
    const candidate = keep.join(" ") || title;
    return candidate.length > maxLen ? candidate.slice(0, maxLen - 1) + "\u2026" : candidate;
  };

  useEffect(() => {
    if (!containerRef.current) return;

    // Filter papers
  const filteredPapers = papers.filter((paper: Paper) => {
      const matchesMission = filters.missions.includes(paper.mission);
      const [minYear, maxYear] = filters.yearRange ?? [Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY];
      const matchesYear = paper.year >= minYear && paper.year <= maxYear;
      const matchesSearch = searchQuery
        ? paper.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
          paper.topics.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()))
        : true;
      return matchesMission && matchesYear && matchesSearch;
    });

    const getMissionColor = (mission: Mission) => {
      switch (mission) {
        case "ISS":
          return "#06b6d4";
        case "Mars":
          return "#f97316";
        case "Moon":
          return "#8b5cf6";
        default:
          return "#8b5cf6";
      }
    };

    // Create cytoscape instance (without running layout yet)
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        // Nodes
        ...filteredPapers.map((paper: Paper) => ({
          data: {
            id: paper.id,
            label: paper.label,
            shortLabel: summarizeTitle(paper.label),
            mission: paper.mission,
            gapScore: paper.gapScore,
            year: paper.year,
          },
        })),
        // Edges
        ...edges
          .filter(
            (edge: Edge) =>
              filteredPapers.some((p: Paper) => p.id === edge.source) &&
              filteredPapers.some((p: Paper) => p.id === edge.target)
          )
          .map((edge: Edge) => ({
            data: {
              id: `${edge.source}-${edge.target}`,
              source: edge.source,
              target: edge.target,
              weight: edge.weight,
            },
          })),
      ],
      style: [
        {
          selector: "node",
          style: {
            label: "data(shortLabel)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "13px",
            color: "#ffffff",
            "text-wrap": "wrap",
            "text-max-width": "140px",
            "background-color": (ele: any) => getMissionColor(ele.data("mission")),
            width: (ele: any) =>
              filters.showGaps ? 80 + ele.data("gapScore") * 100 : 96,
            height: (ele: any) =>
              filters.showGaps ? 80 + ele.data("gapScore") * 100 : 96,
            "border-width": 2,
            "border-color": "#8b5cf6",
            "border-opacity": 0.5,
          },
        },
        {
          selector: "node:active",
          style: {
            "border-width": 4,
            "border-color": "#a78bfa",
            "border-opacity": 1,
          },
        },
        {
          selector: "edge",
          style: {
            width: (ele: any) => ele.data("weight") * 3,
            "line-color": "#8b5cf6",
            "target-arrow-color": "#8b5cf6",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            opacity: 0.4,
          },
        },
      ],
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    });

    // Run layout without animation, then reveal the graph when done
    // Short-circuit if trivial graph to avoid getting stuck
    const trivial = cy.nodes().length <= 1;
    setIsLayingOut(!trivial);
    if (!trivial) {
      const layout = cy.layout({
      name: "cose",
      animate: false,
      randomize: false,
      nodeRepulsion: 1200,
      idealEdgeLength: 50,
      edgeElasticity: 200,
      fit: true,
      padding: 20,
      });

      let cleared = false;
      const clearLoading = () => {
        if (cleared) return;
        cleared = true;
        setIsLayingOut(false);
      };

      // Attach listeners BEFORE running to avoid missing fast events
      cy.one("layoutstop", clearLoading);
      cy.one("ready", () => {
        // In some cases layoutstop might not fire; ready implies render done
        setTimeout(clearLoading, 0);
      });

      // Fallback timeout in case events are missed (dev strict mode, etc.)
      const fallback = window.setTimeout(clearLoading, 2000);
      layout.run();

      // Ensure fallback cleared on destroy
      (cy as any).__layoutFallbackTimer = fallback;
    }

    // Hover tooltip for full label
    cy.on("mouseover", "node", (evt) => {
      const node = evt.target;
      const rp = (evt as any).renderedPosition || (node as any).renderedPosition?.();
      const text = node.data("label");
      if (rp && text) setHoverTip({ x: rp.x + 10, y: rp.y - 10, text });
    });
    cy.on("mouseout", "node", () => setHoverTip(null));
    cy.on("mousemove", "node", (evt) => {
      const rp = (evt as any).renderedPosition;
      if (rp && hoverTip) setHoverTip({ ...hoverTip, x: rp.x + 10, y: rp.y - 10 });
    });

    // Click handler with smooth focus before navigate
    cy.on("tap", "node", (evt) => {
      const node = evt.target;
      const pos = node.position();
      const paperTitle = node.data('label');
      setOverlayLabel(`Opening Paper: ${paperTitle}`);
      setVignette(true);

      // Slow cinematic focus
      cy.animate({
        center: { eles: node },
        zoom: { level: 1.1, position: pos },
        duration: 900,
        easing: 'ease-in-out-cubic',
      });
      setTimeout(() => onPaperClickRef.current(node.id()), 1050);
    });

    cyRef.current = cy;

    return () => {
      // clear any fallback timer
      const t: any = (cy as any).__layoutFallbackTimer;
      if (t) window.clearTimeout(t);
      cy.destroy();
    };
  }, [papers, edges, filters, searchQuery]);

  // Programmatic open of a paper node with the same animation as tap
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !requestOpenPaperId) return;
    const node = cy.getElementById(requestOpenPaperId);
    if (!node || node.empty()) return;
    const pos = node.position();
    const paperTitle = node.data('label');
    setOverlayLabel(`Opening Paper: ${paperTitle}`);
    setVignette(true);
    cy.animate({
      center: { eles: node },
      zoom: { level: 1.1, position: pos },
      duration: 900,
      easing: 'ease-in-out-cubic',
    });
    const t = setTimeout(() => onPaperClickRef.current(requestOpenPaperId), 1050);
    return () => clearTimeout(t);
  }, [requestOpenPaperId, onPaperClick]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="h-full w-full relative"
    >
      {/* Space dust layer for extra depth */}
      <div className="pointer-events-none absolute inset-0 -z-10 opacity-50" style={{ backgroundImage: "radial-gradient(2px 2px at 15% 20%, rgba(255,255,255,0.5), rgba(255,255,255,0) 40%), radial-gradient(1px 1px at 70% 75%, rgba(255,255,255,0.4), rgba(255,255,255,0) 40%), radial-gradient(1.5px 1.5px at 50% 50%, rgba(255,255,255,0.45), rgba(255,255,255,0) 40%)" }} />
      {/* Vignette dimming */}
      {vignette && (
        <div className="pointer-events-none absolute inset-0 z-10" style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 40%, rgba(0,0,0,0.6) 90%)" }} />
      )}

  {/* Graph container; hidden until layout is complete for rock-solid first paint */}
  <div ref={containerRef} className={`h-full w-full transition-opacity ${isLayingOut ? "opacity-0" : "opacity-100"}`} />

      {/* Hover tooltip showing full title */}
      {hoverTip && (
        <div
          className="pointer-events-none absolute z-20 px-2 py-1 rounded bg-black/80 text-white text-xs border border-white/10 shadow-lg"
          style={{ left: hoverTip.x, top: hoverTip.y }}
        >
          {hoverTip.text}
        </div>
      )}

      {/* Loading overlay while computing layout */}
      {isLayingOut && (
        <div className="absolute inset-0 z-20 flex items-center justify-center">
          <div className="flex flex-col items-center gap-3 px-6 py-4 rounded-xl bg-black/60 backdrop-blur border border-white/10 shadow-xl">
            <div className="h-10 w-10 rounded-full border-2 border-white/30 border-t-white animate-spin" />
            <span className="text-white text-sm">Preparing cluster…</span>
          </div>
        </div>
      )}

      {/* Overlay caption */}
      {overlayLabel && (
        <div className="pointer-events-none absolute inset-0 z-20 flex items-center justify-center">
          <div className="px-6 py-3 rounded-full bg-black/60 backdrop-blur text-white border border-white/20 shadow-xl">
            <span className="text-sm md:text-base font-semibold tracking-wide">{overlayLabel}</span>
          </div>
        </div>
      )}
      
      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-card/80 backdrop-blur-sm border border-border rounded-lg p-3 space-y-2">
        <h4 className="text-xs font-semibold mb-2">Mission Colors</h4>
        <div className="flex items-center gap-2 text-xs">
          <div className="w-3 h-3 rounded-full bg-mission-iss" />
          <span>ISS</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className="w-3 h-3 rounded-full bg-mission-mars" />
          <span>Mars</span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <div className="w-3 h-3 rounded-full bg-mission-moon" />
          <span>Moon</span>
        </div>
        {filters.showGaps && (
          <p className="text-xs text-muted-foreground pt-2 border-t border-border">
            Node size = Research gap
          </p>
        )}
      </div>
    </motion.div>
  );
};
