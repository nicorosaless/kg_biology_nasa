import { motion } from "framer-motion";
import { useMemo, useRef, useState } from "react";
import { Cluster, Mission } from "../types/graph";

interface ClusterViewProps {
  clusters: Cluster[];
  onClusterClick: (clusterId: string) => void;
  filters: {
    missions: Mission[];
  };
}

export const ClusterView = ({ clusters, onClusterClick, filters }: ClusterViewProps) => {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [overlayLabel, setOverlayLabel] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const draggingRef = useRef<{ dragging: boolean; lastX: number; lastY: number }>({ dragging: false, lastX: 0, lastY: 0 });
  const getMissionColor = (mission: Mission) => {
    switch (mission) {
      case "ISS":
        return "bg-mission-iss shadow-glow-cyan";
      case "Mars":
        return "bg-mission-mars shadow-glow-purple";
      case "Moon":
        return "bg-mission-moon shadow-glow-soft";
      default:
        return "bg-primary";
    }
  };

  const filteredClusters = clusters.filter((cluster) =>
    filters.missions.includes(cluster.mission)
  );

  // Stable pseudo-random offset based on id to avoid twitching on re-render
  const hashCode = (str: string) => {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
    return h;
  };

  const positions = useMemo(() => {
    const cols = 4;
    const rows = Math.ceil(filteredClusters.length / cols) || 1;
    return filteredClusters.map((c, index) => {
      const row = Math.floor(index / cols);
      const col = index % cols;
      const baseX = (col + 0.5) * (100 / cols);
      const baseY = (row + 0.5) * (100 / rows);
      const h = hashCode(c.id);
      const offsetX = ((h % 1000) / 1000) * 5 - 2.5; // [-2.5, 2.5]
      const offsetY = (((h >> 8) % 1000) / 1000) * 5 - 2.5;
      return { left: `${baseX + offsetX}%`, top: `${baseY + offsetY}%` };
    });
  }, [filteredClusters]);

  // Size based on count
  const getSize = (count: number) => {
    const maxCount = Math.max(...filteredClusters.map((c) => c.count));
    const minSize = 80;
    const maxSize = 180;
    return minSize + ((count / maxCount) * (maxSize - minSize));
  };

  // Pan & Zoom handlers
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = -e.deltaY;
    const zoomFactor = 1 + delta * 0.0015;
    const newScale = Math.min(2.2, Math.max(0.6, scale * zoomFactor));

    // Zoom around cursor
    const rect = containerRef.current?.getBoundingClientRect();
    if (rect) {
      const cx = e.clientX - rect.left;
      const cy = e.clientY - rect.top;
      const tx = (cx - pan.x) / scale;
      const ty = (cy - pan.y) / scale;
      const nx = cx - tx * newScale;
      const ny = cy - ty * newScale;
      setPan({ x: nx, y: ny });
    }
    setScale(newScale);
  };

  const onMouseDown = (e: React.MouseEvent) => {
    draggingRef.current = { dragging: true, lastX: e.clientX, lastY: e.clientY };
  };
  const onMouseMove = (e: React.MouseEvent) => {
    if (!draggingRef.current.dragging) return;
    const dx = e.clientX - draggingRef.current.lastX;
    const dy = e.clientY - draggingRef.current.lastY;
    draggingRef.current.lastX = e.clientX;
    draggingRef.current.lastY = e.clientY;
    setPan((p) => ({ x: p.x + dx, y: p.y + dy }));
  };
  const onMouseUp = () => {
    draggingRef.current.dragging = false;
  };

  return (
    <div className="relative h-full w-full" ref={containerRef} onWheel={onWheel} onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
      {/* Cosmic Background Effect */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-1/4 left-1/4 w-96 h-96 bg-primary/10 rounded-full blur-3xl animate-pulse-glow" />
        <div className="absolute bottom-1/3 right-1/4 w-96 h-96 bg-accent/10 rounded-full blur-3xl animate-pulse-glow delay-1000" />
      </div>

      {/* Clusters */}
      <div
        className="relative h-full"
        style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transformOrigin: "0 0" }}
      >
        {filteredClusters.map((cluster, index) => {
          const position = positions[index] ?? { left: "50%", top: "50%" };
          const size = getSize(cluster.count);

          const isActive = activeId === cluster.id;
          const isDimmed = activeId !== null && !isActive;
          return (
            <motion.div
              key={cluster.id}
              initial={{ opacity: 0, scale: 0.6, filter: "blur(6px)" }}
              animate={{ opacity: isDimmed ? 0.18 : 1, scale: isActive ? 1.25 : isDimmed ? 0.9 : 1, filter: "blur(0px)" }}
              transition={{ delay: index * 0.06, duration: 0.6, ease: "easeOut" }}
              style={{
                position: "absolute",
                ...position,
                width: size,
                height: size,
                transform: "translate(-50%, -50%)",
              }}
              className="cursor-pointer group"
              onClick={() => {
                // Cinematic focus: dim others, enlarge selected, show overlay caption
                setActiveId(cluster.id);
                setOverlayLabel(`Entering Cluster: ${cluster.label}`);
                setTimeout(() => {
                  onClusterClick(cluster.id);
                  // Allow overlay to fade naturally on unmount
                  setTimeout(() => {
                    setActiveId(null);
                    setOverlayLabel(null);
                  }, 200);
                }, 1500); // even longer highlight before entering
              }}
            >
              {/* Glow Effect */}
              <motion.div
                animate={{ scale: isActive ? [1, 1.15, 1.05] : [1, 1.1, 1] }}
                transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
                className={`absolute inset-0 rounded-full ${getMissionColor(
                  cluster.mission
                )} opacity-50 blur-xl`}
              />

              {/* Main Sphere */}
              <div
                className={`relative h-full w-full rounded-full ${getMissionColor(
                  cluster.mission
                )} flex flex-col items-center justify-center p-4 transition-transform group-hover:scale-110 animate-float ${
                  isActive ? "ring-4 ring-white/40 shadow-xl" : ""
                }`}
                style={{
                  animationDelay: `${index * 0.3}s`,
                }}
              >
                <div className="text-center">
                  <h3 className="font-bold text-white text-sm mb-1 drop-shadow-lg">
                    {cluster.label}
                  </h3>
                  <p className="text-xs text-white/90 font-medium">
                    {cluster.count} papers
                  </p>
                </div>

                {/* Hover Details */}
                <div className="absolute inset-0 rounded-full bg-background/95 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center p-4">
                  <h4 className="font-semibold text-sm text-center mb-2">
                    {cluster.label}
                  </h4>
                  <p className="text-xs text-muted-foreground text-center">
                    {cluster.description}
                  </p>
                  <p className="text-xs text-primary mt-2 font-medium">
                    Click to explore →
                  </p>
                </div>

                {/* Slow shimmer ring when active */}
                {isActive && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: [0, 0.5, 0.2], scale: [1, 1.25, 1.1] }}
                    transition={{ duration: 1.0, ease: "easeOut" }}
                    className="absolute inset-0 rounded-full border-4 border-white/50"
                  />
                )}
              </div>

              {/* Orbit Ring */}
              <motion.div
                animate={{ rotate: 360 }}
                transition={{
                  duration: 20 + index * 2,
                  repeat: Infinity,
                  ease: "linear",
                }}
                className="absolute inset-0 rounded-full border border-primary/20"
                style={{ transform: "scale(1.2)" }}
              />
            </motion.div>
          );
        })}
      </div>
      {/* Overlay caption to make destination obvious */}
      {overlayLabel && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="pointer-events-none absolute inset-0 flex items-center justify-center"
        >
          <div className="px-6 py-3 rounded-full bg-black/60 backdrop-blur text-white border border-white/20 shadow-xl">
            <span className="text-sm md:text-base font-semibold tracking-wide">{overlayLabel}</span>
          </div>
        </motion.div>
      )}
    </div>
  );
};
