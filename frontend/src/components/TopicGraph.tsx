import { useEffect, useRef } from "react";
import { motion } from "framer-motion";
import cytoscape from "cytoscape";
import { Paper } from "../types/graph";

interface TopicGraphProps {
  paper: Paper;
}

export const TopicGraph = ({ paper }: TopicGraphProps) => {
  const containerRef = useRef<HTMLDivElement>(null);

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
      <div ref={containerRef} className="h-full w-full" />
      
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
