import { motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";
import { Cluster, Mission } from "../types/graph";

interface ClusterViewProps {
  clusters: Cluster[];
  onClusterClick: (clusterId: string) => void;
  filters: {
    missions: Mission[];
  };
  // Optional: programmatic request to focus a cluster with the same cinematic animation as click
  requestFocusClusterId?: string | null;
}

export const ClusterView = ({ clusters, onClusterClick, filters, requestFocusClusterId }: ClusterViewProps) => {
  const [activeId, setActiveId] = useState<string | null>(null);
  const [overlayLabel, setOverlayLabel] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const [containerSize, setContainerSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  // Deterministic starfield for background
  const stars = useMemo(() => {
    // Small, performant number of stars with subtle variance
    const count = 140;
    // Mulberry32 PRNG for deterministic but well-distributed randoms
    const mulberry32 = (seed: number) => {
      return function () {
        let t = (seed += 0x6d2b79f5);
        t = Math.imul(t ^ (t >>> 15), t | 1);
        t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    };
    const rand = mulberry32(1337);
    return Array.from({ length: count }, (_, i) => {
      const l = rand() * 100; // left %
      const t = rand() * 100; // top %
      const size = 1 + Math.floor(rand() * 2); // 1-2 px
      const opacity = 0.35 + rand() * 0.55; // 0.35 - 0.9
      const dur = 2 + rand() * 3; // 2s - 5s
      const delay = rand() * 5; // 0 - 5s
      return { id: `s${i}`, l, t, size, opacity, dur, delay };
    });
  }, []);
  const draggingRef = useRef<{ dragging: boolean; lastX: number; lastY: number }>({ dragging: false, lastX: 0, lastY: 0 });
  
  // Helper to clean cluster label for display (remove "Macrocluster:" prefix)
  const cleanClusterLabel = (label: string) =>
    label.replace(/^\s*macrocluster\s*:\s*/i, "").trim();
  
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

  // Mission filtering removed; show all clusters regardless of mission.
  const filteredClusters = clusters;

  // Stable pseudo-random offset based on id to avoid twitching on re-render
  const hashCode = (str: string) => {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
    return h;
  };

  const positions = useMemo(() => {
    // If container not measured yet, fallback to centered percents
    if (!containerSize.w || !containerSize.h) {
      return filteredClusters.map(() => ({ left: "50%", top: "50%" }));
    }

    // Constellation-like scrambled layout with deterministic randomness and hard non-overlap
    // Bias area to the left and up to avoid sidebar overlap and bottom touch
    const EXTRA_RIGHT_PAD = Math.round(containerSize.w * 0.10); // keep away from right
    const EXTRA_BOTTOM_PAD = Math.round(containerSize.h * 0.15); // keep away from bottom
    const EXTRA_TOP_PAD = Math.round(containerSize.h * 0.03); // slight raise toward top

    const clamp = (v: number, min: number, max: number) => Math.max(min, Math.min(max, v));
    const hashTo01 = (s: string) => {
      let h = 0x811c9dc5;
      for (let i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 0x01000193);
      }
      return ((h >>> 0) % 0x3fffffff) / 0x3fffffff;
    };

    const minSize = 80;
    const maxSize = 180;
    const counts = filteredClusters.map((c) => c.count);
    const maxCount = counts.length ? Math.max(...counts) : 1;
    const sizePx = (count: number) => minSize + ((count / maxCount) * (maxSize - minSize));

    // Padding from edges so big bubbles don't clip
  const maxRadius = maxSize / 2;
  const EDGE_PAD = 20; // px
    const MARGIN = maxRadius + EDGE_PAD;

    // Build placement order: larger first for easier packing, then id for determinism
    const order = [...filteredClusters].sort((a, b) => {
      const ds = sizePx(b.count) - sizePx(a.count);
      return Math.abs(ds) > 0.1 ? (ds > 0 ? 1 : -1) : a.id.localeCompare(b.id);
    });
    const indexById = new Map(order.map((c, i) => [c.id, i] as const));

  // Generate within a biased coordinate space: reduce right/bottom to push left/up
  const W = containerSize.w;
  const H = containerSize.h;
  const MIN_X = MARGIN;                                  // left bound
  const MAX_X = W - MARGIN - EXTRA_RIGHT_PAD;            // reduced right bound
  const MIN_Y = MARGIN + EXTRA_TOP_PAD;                  // slightly lower top bound (higher on screen)
  const MAX_Y = H - MARGIN - EXTRA_BOTTOM_PAD;           // reduced bottom bound

    const placed: Array<{ x: number; y: number; r: number }> = [];
    const results: Array<{ left: string; top: string }> = [];

    for (const cluster of order) {
      const r = sizePx(cluster.count) / 2;
      // base deterministic position
      const bx = MIN_X + (MAX_X - MIN_X) * hashTo01(cluster.id + "-x");
      const by = MIN_Y + (MAX_Y - MIN_Y) * hashTo01(cluster.id + "-y");

      let cx = bx;
      let cy = by;
      let placedOk = false;

      const PAD = 12; // px between bubbles
      const maxAttempts = 18;
      for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const ang = 2 * Math.PI * hashTo01(cluster.id + "-a-" + attempt);
        // spiral radius grows per attempt
        const rad = attempt * (maxRadius * 0.35);
        const tx = clamp(bx + Math.cos(ang) * rad, MIN_X, MAX_X);
        const ty = clamp(by + Math.sin(ang) * rad, MIN_Y, MAX_Y);

        const hits = placed.some((p) => {
          const dx = p.x - tx;
          const dy = p.y - ty;
          const dist = Math.hypot(dx, dy);
          return dist < (p.r + r + PAD);
        });
        if (!hits) {
          cx = tx;
          cy = ty;
          placedOk = true;
          break;
        }
      }

      // As a last resort, do a deterministic sweep to find any free slot
      if (!placedOk) {
        const grid = 10;
        outer: for (let gy = 0; gy <= grid; gy++) {
          for (let gx = 0; gx <= grid; gx++) {
            const tx = MIN_X + (gx / grid) * (MAX_X - MIN_X);
            const ty = MIN_Y + (gy / grid) * (MAX_Y - MIN_Y);
            const hits = placed.some((p) => Math.hypot(p.x - tx, p.y - ty) < (p.r + r + 8));
            if (!hits) { cx = tx; cy = ty; placedOk = true; break outer; }
          }
        }
      }

      placed.push({ x: cx, y: cy, r });
      results[indexById.get(cluster.id) ?? 0] = { left: `${Math.round(cx)}px`, top: `${Math.round(cy)}px` };
    }

    // Map back to original filtered order
    return filteredClusters.map((c) => results[indexById.get(c.id) ?? 0] || { left: "50%", top: "50%" });
  }, [filteredClusters, containerSize.w, containerSize.h]);

  // Track container size for accurate pixel-based layout
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => {
      const rect = el.getBoundingClientRect();
      setContainerSize({ w: Math.max(0, Math.floor(rect.width)), h: Math.max(0, Math.floor(rect.height)) });
    };
    update();
    const ro = new ResizeObserver(() => update());
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

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

  // Programmatic focus animation when a tool event requests opening a cluster from the universe view
  useMemo(() => {
    if (!requestFocusClusterId) return;
    const target = filteredClusters.find((c) => c.id === requestFocusClusterId);
    if (!target) return;
    // Trigger the same cinematic focus as a user click
    setActiveId(target.id);
    setOverlayLabel(`Entering Cluster: ${cleanClusterLabel(target.label)}`);
    const t = setTimeout(() => {
      onClusterClick(target.id);
      setTimeout(() => {
        setActiveId(null);
        setOverlayLabel(null);
      }, 200);
    }, 1200);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestFocusClusterId]);

  return (
    <div className="relative h-full w-full" ref={containerRef} onWheel={onWheel} onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
      {/* Local keyframes for star twinkle */}
      <style>
        {`
        @keyframes twinkle { 0% { opacity: 0.25; transform: scale(1) } 50% { opacity: 0.85 } 100% { opacity: 0.25; transform: scale(1.05) } }
        `}
      </style>
      {/* Cosmic Background Effect */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {/* Starfield */}
        <div className="absolute inset-0">
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
                setOverlayLabel(`Entering Cluster: ${cleanClusterLabel(cluster.label)}`);
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
                    {cleanClusterLabel(cluster.label)}
                  </h3>
                  <p className="text-xs text-white/90 font-medium">
                    {cluster.count} papers
                  </p>
                </div>

                {/* Hover Details */}
                <div className="absolute inset-0 rounded-full bg-background/95 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center p-4">
                  <h4 className="font-semibold text-sm text-center mb-2">
                    {cleanClusterLabel(cluster.label)}
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
