import React, { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
try { const fcose = require('cytoscape-fcose'); if (fcose) cytoscape.use(fcose); } catch {}
import type { Paper } from '../types/graph';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';
import { Phase5Graph } from './Phase5Graph';

// ---------- Types ----------
interface FigureItem { id: string; caption?: string; label?: string; image_path?: string; path?: string; order?: number }
interface SummarySection { heading?: string; summary?: string; figures?: FigureItem[] }
interface RemoteSummaryMeta { intro?: any; sections?: SummarySection[]; conclusion?: string | { summary?: string }; _meta?: { paper_title?: string; word_count?: number; figures?: string[] } }
interface GraphNode { id: number | string; label: string; type?: string }
interface GraphEdge { source: number | string; target: number | string; id?: string }
interface GraphDataCore { nodes: GraphNode[]; edges: GraphEdge[] }
interface SectionOverviewEntry { id: number; section: string; relations: number }
interface SectionOverview { sections: SectionOverviewEntry[] }

export const PaperDetail = ({ paper }: { paper: Paper }) => {
  // ---------- State ----------
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<RemoteSummaryMeta | null>(null);
  const [overviewGraph, setOverviewGraph] = useState<GraphDataCore | null>(null);
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [sectionsOverview, setSectionsOverview] = useState<SectionOverviewEntry[]>([]);
  const [currentSection, setCurrentSection] = useState<string | 'OVERVIEW'>('OVERVIEW');
  // PDF source (we mutate with #page + cache-busting param to force internal viewer to jump)
  const [pdfObjectUrl, setPdfObjectUrl] = useState<string | null>(null);
  const [pdfInlineError, setPdfInlineError] = useState<string | null>(null);
  const pendingPageRef = useRef<number | null>(null);
  const [figureModal, setFigureModal] = useState<{id:string; src:string; caption?:string; label?:string; number?:number} | null>(null);
  const [activeTab, setActiveTab] = useState<string>('summary');
  const [toast, setToast] = useState<string | null>(null);

  // ---------- Refs ----------
  const cyRef = useRef<cytoscape.Core | null>(null);
  const cyContainerRef = useRef<HTMLDivElement>(null);

  // ---------- Backend URLs ----------
  const backendBase = useMemo(() => {
    const env = import.meta.env.VITE_BACKEND_URL?.replace(/\/$/, '') || '';
    if (env) return env;
    // Fallback heuristic: assume backend same host but port 8000
    try {
      const loc = window.location;
      return `${loc.protocol}//${loc.hostname}:8000`;
    } catch { return 'http://localhost:8000'; }
  }, []);
  const pdfUrl = `${backendBase}/api/paper/${paper.id}/pdf`;
  const summaryUrl = `${backendBase}/api/paper/${paper.id}/summary?run=false`;
  const overviewUrl = `${backendBase}/api/paper/${paper.id}/graph/overview`;
  const sectionsUrl = `${backendBase}/api/paper/${paper.id}/sections`;

  // ---------- Data Loading ----------
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true); setError(null);
      try {
        // Fetch summary & section overview first
        const [sRes, secRes] = await Promise.all([
          fetch(summaryUrl), fetch(sectionsUrl)
        ]);
        if (!sRes.ok) throw new Error(`Summary ${sRes.status}`);
        const sJson = await sRes.json();
        let secJson: SectionOverview | null = null;
        if (secRes.ok) { try { secJson = await secRes.json(); } catch {} }
        if (!cancelled) {
          setSummary(sJson);
          if (secJson?.sections) setSectionsOverview(secJson.sections);
        }
        // Try overview graph
        const ov = await fetch(overviewUrl);
        if (ov.ok) {
          const gJson = await ov.json();
          if (!cancelled) setOverviewGraph(gJson);
        } else if (ov.status === 404) {
          // Fallback: fetch core graph and derive a reduced overview
            const coreUrl = `${backendBase}/api/paper/${paper.id}/graph?core=true`;
            const coreRes = await fetch(coreUrl);
            if (coreRes.ok) {
              const coreJson = await coreRes.json();
              const reduced = reduceCore(coreJson, 40);
              if (!cancelled) setOverviewGraph(reduced);
            }
        } else {
          // Other error codes -> soft report
          if (!cancelled) console.warn('Overview graph fetch failed', ov.status);
        }
      } catch (e:any) {
        if (!cancelled) {
          // Only set global error if summary ALSO failed (summary already thrown). If summary succeeded we leave summary visible.
          if (!summary) setError(e.message || 'Load error');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [summaryUrl, overviewUrl, sectionsUrl, paper.id, backendBase]);

  // Client-side reducer for graph_core.json -> overview style (≤ limit)
  function reduceCore(core: any, limit: number): GraphDataCore {
    const nodes = (core.nodes || []).map((n: any) => ({ id: n.id, label: n.label, type: n.type, nav: n.nav, freq: n.freq }));
    const edges = core.edges || [];
    const deg: Record<string, number> = {};
    edges.forEach((e: any) => { const s = String(e.source), t = String(e.target); deg[s]=(deg[s]||0)+1; deg[t]=(deg[t]||0)+1; });
    const scored = nodes.map(n => ({ n, d: deg[String(n.id)]||0, f: n.freq||1 }));
    scored.sort((a,b) => (b.d - a.d) || (b.f - a.f));
    const sel = new Set(scored.slice(0, limit).map(s => String(s.n.id)));
    const outNodes = scored.slice(0, limit).map(s => ({ id: s.n.id, label: s.n.label, type: s.n.type, nav: s.n.nav }));
    const outEdges = edges.filter((e: any) => sel.has(String(e.source)) && sel.has(String(e.target))).map((e: any, i: number) => ({ id: e.id || `e${i}`, source: e.source, target: e.target }));
    return { nodes: outNodes as any, edges: outEdges as any };
  }

  // ---------- PDF Loading (direct URL; allows #page anchor navigation) ----------
  useEffect(() => {
    // Initial load without specific page; subsequent navigation events will re-set with #page and timestamp
    setPdfObjectUrl(pdfUrl);
    setPdfInlineError(null);
  }, [pdfUrl, paper.id]);

  // ---------- Graph (Cytoscape) ----------
  function buildCy(g: GraphDataCore) {
    if (!cyContainerRef.current) return;
    if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null; }
    const deg: Record<string, number> = {};
    g.edges.forEach(e => { const s = String(e.source), t = String(e.target); deg[s]=(deg[s]||0)+1; deg[t]=(deg[t]||0)+1; });
    const elements: cytoscape.ElementDefinition[] = [
      ...g.nodes.map(n => ({ data: { id: String(n.id), label: (n.label||'').slice(0,30), type: n.type || 'ENTITY', section: (n as any).nav?.section || null, degree: deg[String(n.id)] || 0 } })),
      ...g.edges.map((e,i) => ({ data: { id: e.id || `e-${i}`, source: String(e.source), target: String(e.target) } }))
    ];
    cyRef.current = cytoscape({
      container: cyContainerRef.current,
      elements,
      style: [
        { selector: 'node', style: { 'background-color': '#2563eb', label: 'data(label)', 'font-size': '9px', color: '#fff', 'text-wrap': 'wrap', 'text-max-width': '120px', 'width': 'mapData(degree, 0, 25, 12, 30)', 'height': 'mapData(degree, 0, 25, 12, 30)', 'border-width': 1, 'border-color': '#1e3a8a' } },
        { selector: 'node[type = "GENE_PRODUCT"]', style: { 'background-color': '#1f77b4' } },
        { selector: 'node[type = "EXPERIMENT"]', style: { 'background-color': '#ff7f0e' } },
        { selector: 'node[type = "PHENOTYPE"]', style: { 'background-color': '#9467bd' } },
        { selector: 'node[type = "CELL_TYPE"]', style: { 'background-color': '#2ca02c' } },
        { selector: 'node[type = "ANATOMICAL_SITE"]', style: { 'background-color': '#8c564b' } },
  { selector: 'node[type = "PUBLICATION"]', style: { 'background-color': '#bcbd22', 'shape': 'diamond' } },
  { selector: 'edge', style: { width: 1, 'line-color': '#64748b', opacity: 0.55 } },
  { selector: ':selected', style: { 'border-width': 3, 'border-color': '#fbbf24' } },
    { selector: 'node.hovered', style: { 'border-width': 3, 'border-color': '#f59e0b' } },
      ],
      layout: { name: ((cytoscape as any).fcose ? 'fcose' : 'cose'), animate: false },
      wheelSensitivity: 0.2
    });
    // Hover effect with throttled highlight
  cyRef.current.on('mouseover', 'node', evt => { evt.target.addClass('hovered'); });
  cyRef.current.on('mouseout', 'node', evt => { evt.target.removeClass('hovered'); });
    // Double click (two taps) -> load section subgraph if node has section
    let lastTap: number | null = null;
    cyRef.current.on('tap', 'node', evt => {
      const now = Date.now();
      if (lastTap && now - lastTap < 350) { // double
        const sec = evt.target.data('section');
        if (sec) {
          setCurrentSection(sec);
          setActiveSection(sec);
        }
      }
      lastTap = now;
    });
  }
  useEffect(() => { if (overviewGraph) buildCy(overviewGraph); }, [overviewGraph]);

  // Per-section subgraph fetch
  useEffect(() => {
  if (!overviewGraph) return;
  if (currentSection === 'OVERVIEW') { if (overviewGraph && cyRef.current) buildCy(overviewGraph); return; }
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${backendBase}/api/paper/${paper.id}/graph/section/${encodeURIComponent(currentSection)}`);
        if (!r.ok) throw new Error('Section graph');
        const j = await r.json(); if (cancelled) return;
        const sg: GraphDataCore = { nodes: j.nodes || [], edges: j.edges || [] }; buildCy(sg);
      } catch { /* ignore */ }
    })();
    return () => { cancelled = true; };
  }, [currentSection, backendBase, paper.id, overviewGraph]);

  // Hash navigation after summary load
  useEffect(() => {
    if (!summary) return;
    const hash = window.location.hash?.replace('#','');
    if (!hash) return;
    const el = document.getElementById(hash);
    if (el) setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 120);
  }, [summary]);

  const title = summary?._meta?.paper_title || paper.label;

  // Plain text assembly (intro + each section heading: summary + conclusion)
  const plainSummary = useMemo(() => {
    if (!summary) return '';
    const parts: string[] = [];
    // Intro may be object with summary field
    if (summary.intro) {
      if (typeof summary.intro === 'string') parts.push(summary.intro.trim());
      else if (summary.intro.summary) parts.push(String(summary.intro.summary).trim());
    }
    if (Array.isArray(summary.sections)) {
      for (const sec of summary.sections) {
        if (!sec) continue;
        const h = sec.heading?.trim();
        const s = sec.summary?.trim();
        if (h && s) parts.push(`${h}: ${s}`);
        else if (h) parts.push(h);
        else if (s) parts.push(s);
      }
    }
    if (summary.conclusion) {
      if (typeof summary.conclusion === 'string') parts.push(summary.conclusion.trim());
      else if (summary.conclusion.summary) parts.push(String(summary.conclusion.summary).trim());
    }
    return parts.join('\n\n');
  }, [summary]);

  // Collect type filters UI (derive from current graph nodes)
  // Removed filters & modes for minimal stable visualization

  // Listener: navigate from graph node detail to summary section
  useEffect(()=> {
    const handler = (e: any) => {
      const det = e.detail || {};
      if (!det || det.paperId !== paper.id) return;
      const sectionName: string | undefined = det.section;
      const page: number | undefined = det.page || det.nav?.page;
      if (page) {
        // Force a full reload of the embedded PDF with the target page hash.
        // Add a transient cache-busting query param to ensure Chrome's built-in viewer re-parses the hash.
        const base = pdfUrl.split('#')[0];
        const ts = Date.now();
        const newSrc = `${base}?v=${ts}#page=${page}`;
        // If same as existing (rare because timestamp changes) we still set to trigger React re-render.
        setPdfObjectUrl(newSrc);
        // In case iframe not mounted yet, remember page (will be applied again on load just in case)
        pendingPageRef.current = page;
        setActiveTab('graph');
      } else {
        setToast('No page info for this section');
        setTimeout(()=> setToast(null), 2200);
      }
      // Do NOT switch tabs automatically anymore.
    };
    window.addEventListener('phase5:locate-pdf', handler);
    return ()=> window.removeEventListener('phase5:locate-pdf', handler);
  }, [paper.id, pdfUrl]);

  return (
    <div className="w-full p-2 md:p-4">
      <div className="w-full grid grid-cols-1 md:grid-cols-[40%_1fr] gap-4 items-start">
        {/* LEFT: PDF */}
  <div className="md:sticky md:top-2 md:self-start w-full flex flex-col border border-border/50 rounded-md bg-card/40 overflow-hidden max-h-[95vh]">
          <div className="h-11 flex items-center px-3 border-b border-border/50 text-xs gap-2">
            <span className="font-medium">PDF</span>
            <div className="ml-auto flex items-center gap-1.5">
              {pdfObjectUrl && <a href={pdfUrl} target="_blank" rel="noreferrer" className="underline hover:no-underline">Open</a>}
            </div>
          </div>
            <div className="flex-1 relative h-[85vh] min-h-[70vh]">
              {pdfObjectUrl && !pdfInlineError && (
                  <iframe
                  key={pdfObjectUrl}
                  src={pdfObjectUrl}
                  className="absolute inset-0 w-full h-full"
                  title="PDF preview"
                  onLoad={(e)=> {
                    // If we had a pending page (event fired before iframe ready) and current src lacks it, re-issue.
                    if (pendingPageRef.current) {
                      const cur = e.currentTarget.getAttribute('src') || '';
                      if (!/#[^#]*page=/.test(cur)) {
                        const base = (cur.split('#')[0] || pdfUrl).split('?')[0];
                        const ts = Date.now();
                        e.currentTarget.setAttribute('src', `${base}?v=${ts}#page=${pendingPageRef.current}`);
                      }
                      pendingPageRef.current = null;
                    }
                  }}
                  onError={() => {
                    // Fallback: try object embedding
                    setPdfInlineError('iframe-failed');
                  }}
                />
              )}
              {pdfInlineError === 'iframe-failed' && pdfObjectUrl && (
                <object data={pdfObjectUrl} type="application/pdf" className="absolute inset-0 w-full h-full" aria-label="PDF object fallback">
                  <div className="p-3 text-[11px] text-muted-foreground">PDF viewer fallback failed. <a className='underline' href={pdfObjectUrl} target='_blank' rel='noreferrer'>Open in new tab</a></div>
                </object>
              )}
              {!pdfObjectUrl && !pdfInlineError && (
                <div className="flex items-center justify-center h-full text-xs text-muted-foreground">Loading PDF...</div>
              )}
              {pdfInlineError && (
                <div className="p-3 text-[11px] text-red-500">{pdfInlineError}</div>
              )}
            </div>
        </div>
        {/* RIGHT: Tabs */}
        <div className="w-full flex flex-col">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col w-full">
            <div className="h-11 flex items-center px-3 border-b border-border/50 bg-background/70 sticky top-0 z-10">
              <TabsList className="h-8">
                <TabsTrigger value="summary">Summary</TabsTrigger>
                <TabsTrigger value="graph">Graph</TabsTrigger>
              </TabsList>
              <div className="ml-auto flex items-center gap-2 text-[11px]">
                {summary && <span className="text-muted-foreground">{summary._meta?.word_count} words</span>}
              </div>
            </div>
            <TabsContent
              value="summary"
              className="w-full p-4 overflow-y-auto max-h-[calc(100vh-3.5rem)] pr-2"
            >
              {loading && <div className="text-xs text-muted-foreground">Loading summary...</div>}
              {error && <div className="text-xs text-red-500">{error}</div>}
              {!loading && summary && (
                <article className="max-w-4xl whitespace-pre-wrap text-sm leading-relaxed font-normal">
                  <h2 className="text-base font-semibold mb-4" id="paper-title">{title}</h2>
                  {plainSummary}
                </article>
              )}
            </TabsContent>
            <TabsContent value="graph" className="w-full p-3 flex flex-col gap-3">
              <div className="flex items-center justify-between text-[11px]">
                <div className="flex items-center gap-2">
                  {currentSection !== 'OVERVIEW' && (
                    <button onClick={() => { setCurrentSection('OVERVIEW'); setActiveSection(null); if (overviewGraph) buildCy(overviewGraph); }} className="px-2 py-1 rounded border text-xs bg-background/60 hover:bg-background">← Overview</button>
                  )}
                  <span className="text-muted-foreground">{currentSection === 'OVERVIEW' ? 'Overview graph (≤40 nodes)' : `Section: ${currentSection}`}</span>
                </div>
                <div className="text-[10px] text-muted-foreground hidden md:block">Double‑click un nodo con sección para abrir su subgrafo</div>
              </div>
              {/* Phase5 Graph Tab */}
              <div className='h-[650px] w-full'>
                <Phase5Graph paperId={paper.id} />
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </div>
      {figureModal && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setFigureModal(null)}>
          <div className="relative max-w-4xl w-full bg-background rounded-lg shadow-xl border border-border overflow-hidden" onClick={e => e.stopPropagation()}>
            <button className="absolute top-2 right-2 text-xs px-2 py-1 bg-black/50 text-white rounded hover:bg-black/70" onClick={() => setFigureModal(null)}>Close</button>
            <div className="max-h-[75vh] overflow-auto p-4 space-y-4">
              <h4 className="text-sm font-semibold">Figure {figureModal.number || ''}{figureModal.label ? ` ${figureModal.label}` : ''}</h4>
              <div className="w-full bg-black/5 rounded flex items-center justify-center p-2">
                <img src={figureModal.src} alt={figureModal.caption?.slice(0,140) || figureModal.label || figureModal.id} className="max-h-[60vh] object-contain" />
              </div>
              {figureModal.caption && <p className="text-xs leading-relaxed whitespace-pre-line text-muted-foreground">{figureModal.caption}</p>}
              <div className="flex gap-3 text-[11px]">
                <button onClick={() => { const a = document.createElement('a'); a.href = figureModal.src; a.download = `${figureModal.id}.png`; a.click(); }} className="px-2 py-1 rounded border bg-background/50 hover:bg-background">Download</button>
                <button onClick={() => { navigator.clipboard.writeText(window.location.href.split('#')[0] + `#fig-${figureModal.id}`); }} className="px-2 py-1 rounded border bg-background/50 hover:bg-background">Copy link</button>
              </div>
            </div>
          </div>
        </div>
      )}
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 bg-black/80 text-white text-xs px-3 py-2 rounded shadow">
          {toast}
        </div>
      )}
    </div>
  );
};
