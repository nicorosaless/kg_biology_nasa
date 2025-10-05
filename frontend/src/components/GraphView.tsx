import { useEffect, useMemo, useRef, useState } from "react";
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
  // Deterministic starfield for background
  const stars = useMemo(() => {
    const count = 140;
    const mulberry32 = (seed: number) => {
      return function () {
        let t = (seed += 0x6d2b79f5);
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    };
    const rand = mulberry32(20241005);
    return Array.from({ length: count }, (_, i) => {
      const l = rand() * 100;
      const t = rand() * 100;
      const size = 1 + Math.floor(rand() * 2);
      const opacity = 0.35 + rand() * 0.55;
      const dur = 2 + rand() * 3;
      const delay = rand() * 5;
      return { id: `gv_s${i}`, l, t, size, opacity, dur, delay };
    });
  }, []);

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

    // Filter papers (mission filter removed)
    const filteredPapers = papers.filter((paper: Paper) => {
      const [minYear, maxYear] = filters.yearRange ?? [Number.NEGATIVE_INFINITY, Number.POSITIVE_INFINITY];
      const matchesYear = paper.year >= minYear && paper.year <= maxYear;
      const matchesSearch = searchQuery
        ? paper.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
          paper.topics.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()))
        : true;
      return matchesYear && matchesSearch;
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

    // Adjust color brightness based on gap score (higher gap = lighter, lower gap = darker)
    const getNodeColor = (mission: Mission, gapScore: number) => {
      if (!filters.showGaps) {
        return getMissionColor(mission);
      }
      
      const baseColor = getMissionColor(mission);
      
      // Parse hex color to RGB
      const r = parseInt(baseColor.slice(1, 3), 16);
      const g = parseInt(baseColor.slice(3, 5), 16);
      const b = parseInt(baseColor.slice(5, 7), 16);
      
      // Map gap score (0-1) to brightness adjustment with more dramatic range
      // Higher gap score (0.7-1.0) → much lighter (1.0-1.8x)
      // Lower gap score (0-0.3) → much darker (0.4-1.0x)
      const factor = 0.4 + (gapScore * 1.4);
      
      // Apply brightness adjustment
      const newR = Math.min(255, Math.round(r * factor));
      const newG = Math.min(255, Math.round(g * factor));
      const newB = Math.min(255, Math.round(b * factor));
      
      return `rgb(${newR}, ${newG}, ${newB})`;
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
          selector: 'core',
          style: {
            'background-color': 'transparent',
            'selection-box-color': '#8b5cf6',
            'selection-box-opacity': 0.15,
            'active-bg-opacity': 0,
          },
        },
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
            "background-color": (ele: any) => getNodeColor(ele.data("mission"), ele.data("gapScore")),
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

    // Ensure all canvases are transparent (some themes may set a background)
    try {
      const host = containerRef.current as HTMLElement;
      const canvases = host?.querySelectorAll?.('canvas');
      canvases?.forEach((c: any) => {
        (c as HTMLCanvasElement).style.background = 'transparent';
      });
      (host as HTMLElement).style.background = 'transparent';
    } catch {}

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
      {/* Force cytoscape canvas layers to be transparent so stars remain visible */}
      <style>
        {`
          [data-canvas-transparent] { background: transparent !important; }
          [data-canvas-transparent] canvas { background: transparent !important; }
        `}
      </style>
      {/* Starfield keyframes */}
      <style>
        {`
        @keyframes twinkle { 0% { opacity: 0.25; transform: scale(1) } 50% { opacity: 0.85 } 100% { opacity: 0.25; transform: scale(1.05) } }
        `}
      </style>
      {/* Starfield background */}
  <div className="pointer-events-none absolute inset-0" style={{ zIndex: 0 }}>
        {stars.map((s) => (
          <div
            key={s.id}
            className="absolute rounded-full"
            style={{
              left: `${s.l}%`,
              top: `${s.t}%`,
              width: `${s.size}px`,
              height: `${s.size}px`,
              background: "rgba(255,255,255,0.95)",
              boxShadow: "0 0 4px rgba(255,255,255,0.6)",
              opacity: s.opacity,
              animation: `twinkle ${s.dur}s ease-in-out ${s.delay}s infinite alternate`,
            }}
          />
        ))}
      </div>
      {/* Space dust layer for extra depth */}
      <div className="pointer-events-none absolute inset-0 -z-10 opacity-50" style={{ backgroundImage: "radial-gradient(2px 2px at 15% 20%, rgba(255,255,255,0.5), rgba(255,255,255,0) 40%), radial-gradient(1px 1px at 70% 75%, rgba(255,255,255,0.4), rgba(255,255,255,0) 40%), radial-gradient(1.5px 1.5px at 50% 50%, rgba(255,255,255,0.45), rgba(255,255,255,0) 40%)" }} />
      {/* Vignette dimming */}
      {vignette && (
        <div className="pointer-events-none absolute inset-0 z-10" style={{ background: "radial-gradient(ellipse at center, rgba(0,0,0,0) 40%, rgba(0,0,0,0.6) 90%)" }} />
      )}

  {/* Graph container; hidden until layout is complete for rock-solid first paint */}
  <div ref={containerRef} data-canvas-transparent className={`h-full w-full transition-opacity ${isLayingOut ? "opacity-0" : "opacity-100"}`} style={{ background: "transparent", zIndex: 1, position: 'relative' }} />

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
      {filters.showGaps && (
        <div className="absolute bottom-4 left-4 bg-card/80 backdrop-blur-sm border border-border rounded-lg p-3 space-y-1">
          <p className="text-xs text-muted-foreground">
            Size = Research gap
          </p>
          <p className="text-xs text-muted-foreground">
            Brightness = Gap magnitude
          </p>
          <p className="text-[10px] text-muted-foreground/70">
            (Lighter = higher gap)
          </p>
        </div>
      )}
    </motion.div>
  );
};
