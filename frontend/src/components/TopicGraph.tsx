import { useEffect, useMemo, useRef } from "react";
import { motion } from "framer-motion";
import cytoscape from "cytoscape";
import { Paper } from "../types/graph";

interface TopicGraphProps {
  paper: Paper;
}

export const TopicGraph = ({ paper }: TopicGraphProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  // Deterministic starfield for background
  const stars = useMemo(() => {
    const count = 120;
    const mulberry32 = (seed: number) => {
      return function () {
        let t = (seed += 0x6d2b79f5);
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    };
    // Seed with paper id to get a unique but stable background per paper
    let seed = 0;
    for (let i = 0; i < paper.id.length; i++) seed = (seed * 31 + paper.id.charCodeAt(i)) >>> 0;
    const rand = mulberry32(seed || 424242);
    return Array.from({ length: count }, (_, i) => {
      const l = rand() * 100;
      const t = rand() * 100;
      const size = 1 + Math.floor(rand() * 2);
      const opacity = 0.35 + rand() * 0.55;
      const dur = 2 + rand() * 3;
      const delay = rand() * 5;
      return { id: `tg_s${i}`, l, t, size, opacity, dur, delay };
    });
  }, [paper.id]);

  useEffect(() => {
    if (!containerRef.current) return;

    // Create topic nodes from paper topics
    const topicNodes = paper.topics.map((topic, index) => ({
      data: {
        id: `topic-${index}`,
        label: topic,
        type: "topic",
      },
    }));

    // Add the main paper node
    const paperNode = {
      data: {
        id: paper.id,
        label: paper.label,
        type: "paper",
      },
    };

    // Create edges from paper to all topics
    const edges = paper.topics.map((_, index) => ({
      data: {
        id: `${paper.id}-topic-${index}`,
        source: paper.id,
        target: `topic-${index}`,
      },
    }));

    const cy = cytoscape({
      container: containerRef.current,
      elements: [...topicNodes, paperNode, ...edges],
      style: [
        {
          selector: 'node[type="paper"]',
          style: {
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "12px",
            "font-weight": "bold",
            color: "#ffffff",
            "text-wrap": "wrap",
            "text-max-width": "120px",
            "background-color": "#8b5cf6",
            width: 80,
            height: 80,
            "border-width": 3,
            "border-color": "#a78bfa",
          },
        },
        {
          selector: 'node[type="topic"]',
          style: {
            label: "data(label)",
            "text-valign": "center",
            "text-halign": "center",
            "font-size": "10px",
            color: "#ffffff",
            "text-wrap": "wrap",
            "text-max-width": "80px",
            "background-color": "#06b6d4",
            width: 60,
            height: 60,
            "border-width": 2,
            "border-color": "#22d3ee",
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#8b5cf6",
            opacity: 0.6,
            "curve-style": "bezier",
          },
        },
      ],
      layout: {
        name: "circle",
        animate: true,
        animationDuration: 1000,
        radius: 150,
      },
      userZoomingEnabled: true,
      userPanningEnabled: true,
      boxSelectionEnabled: false,
    });

    // Ensure all canvases are transparent so stars remain visible
    try {
      const host = containerRef.current as HTMLElement;
      const canvases = host?.querySelectorAll?.('canvas');
      canvases?.forEach((c: any) => {
        (c as HTMLCanvasElement).style.background = 'transparent';
      });
      (host as HTMLElement).style.background = 'transparent';
    } catch {}

    // Center on paper node
    cy.center(cy.$(`#${paper.id}`));
    cy.fit(cy.elements(), 50);

    return () => {
      cy.destroy();
    };
  }, [paper]);

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
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
      <div className="pointer-events-none absolute inset-0" style={{ zIndex: -5 }}>
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
  <div ref={containerRef} data-canvas-transparent className="h-full w-full" style={{ background: "transparent" }} />
      
      {/* Info overlay */}
      <div className="absolute top-4 left-4 bg-card/80 backdrop-blur-sm border border-border rounded-lg p-3 max-w-xs">
        <h4 className="text-sm font-semibold mb-1">Topic Graph</h4>
        <p className="text-xs text-muted-foreground">
          Exploring key concepts within this paper. Each topic node represents a research area
          or methodology discussed in the study.
        </p>
      </div>
    </motion.div>
  );
};
