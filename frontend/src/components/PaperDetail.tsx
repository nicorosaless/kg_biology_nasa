import React, { useEffect, useMemo, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import type { Paper } from '../types/graph';
import { Tabs, TabsList, TabsTrigger, TabsContent } from './ui/tabs';

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
  const [graph, setGraph] = useState<GraphDataCore | null>(null);
  const [sectionsOverview, setSectionsOverview] = useState<SectionOverviewEntry[]>([]);
  const [currentSection, setCurrentSection] = useState<string | 'ALL'>('ALL');
  const [pdfObjectUrl, setPdfObjectUrl] = useState<string | null>(null);
  const [pdfInlineError, setPdfInlineError] = useState<string | null>(null);
  const [figureModal, setFigureModal] = useState<{id:string; src:string; caption?:string; label?:string; number?:number} | null>(null);

  // ---------- Refs ----------
  const cyRef = useRef<cytoscape.Core | null>(null);
  const cyContainerRef = useRef<HTMLDivElement>(null);

  // ---------- Backend URLs ----------
  const backendBase = useMemo(() => (import.meta.env.VITE_BACKEND_URL?.replace(/\/$/, '') || ''), []);
  const pdfUrl = `${backendBase}/api/paper/${paper.id}/pdf`;
  const summaryUrl = `${backendBase}/api/paper/${paper.id}/summary?run=false`;
  const graphUrl = `${backendBase}/api/paper/${paper.id}/graph?core=true&run=false`;
  const sectionsUrl = `${backendBase}/api/paper/${paper.id}/sections`;

  // ---------- Data Loading ----------
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true); setError(null);
      try {
        const [sRes, gRes, secRes] = await Promise.all([
          fetch(summaryUrl), fetch(graphUrl), fetch(sectionsUrl)
        ]);
        if (!sRes.ok) throw new Error(`Summary ${sRes.status}`);
        if (!gRes.ok) throw new Error(`Graph ${gRes.status}`);
        const sJson = await sRes.json();
        const gJson = await gRes.json();
        let secJson: SectionOverview | null = null;
        if (secRes.ok) { try { secJson = await secRes.json(); } catch { /* ignore */ } }
        if (!cancelled) {
          setSummary(sJson);
          setGraph(gJson);
          if (secJson?.sections) setSectionsOverview(secJson.sections);
        }
      } catch (e:any) { if (!cancelled) setError(e.message || 'Load error'); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [summaryUrl, graphUrl, sectionsUrl, paper.id]);

  // ---------- PDF Loading ----------
  useEffect(() => {
    let cancelled = false; let revoke: string | null = null;
    (async () => {
      try {
        const r = await fetch(pdfUrl); if (!r.ok) throw new Error(`PDF ${r.status}`);
        const blob = await r.blob(); if (cancelled) return;
        const url = URL.createObjectURL(blob); setPdfObjectUrl(url); revoke = url;
      } catch (e:any) { if (!cancelled) setPdfInlineError(e.message); }
    })();
    return () => { cancelled = true; if (revoke) URL.revokeObjectURL(revoke); };
  }, [pdfUrl, paper.id]);

  // ---------- Graph (Cytoscape) ----------
  function buildCy(g: GraphDataCore) {
    if (!cyContainerRef.current) return;
    if (cyRef.current) { cyRef.current.destroy(); cyRef.current = null; }
    const elements = [
      ...g.nodes.map(n => ({ data: { id: String(n.id), label: n.label, type: n.type || 'entity', section: (n as any).nav?.section || (n as any).section || null } })),
      ...g.edges.map((e,i) => ({ data: { id: e.id || `e-${i}`, source: String(e.source), target: String(e.target) } }))
    ];
    cyRef.current = cytoscape({
      container: cyContainerRef.current,
      elements,
      style: [
        { selector: 'node', style: { 'background-color': '#2563eb', label: 'data(label)', 'font-size': '8px', color: '#fff', 'text-wrap': 'wrap', 'text-max-width': '120px' } },
        { selector: 'edge', style: { width: 1, 'line-color': '#94a3b8', opacity: 0.6 } },
        { selector: ':selected', style: { 'border-width': 2, 'border-color': '#f59e0b' } }
      ],
      layout: { name: 'cose', animate: false },
      wheelSensitivity: 0.2
    });
    // Node click -> navigate to its section subgraph (if available)
    cyRef.current.on('tap', 'node', evt => {
      const sec = evt.target.data('section');
      if (sec && typeof sec === 'string') {
        setCurrentSection(sec);
      }
    });
  }
  useEffect(() => { if (graph) buildCy(graph); }, [graph]);

  // Per-section subgraph fetch
  useEffect(() => {
    if (currentSection === 'ALL') { if (graph && cyRef.current) buildCy(graph); return; }
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
  }, [currentSection, backendBase, paper.id, graph]);

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
                  src={pdfObjectUrl}
                  className="absolute inset-0 w-full h-full"
                  title="PDF preview"
                />
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
          <Tabs defaultValue="summary" className="flex flex-col w-full">
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
              {!loading && !error && summary && (
                <article className="max-w-4xl whitespace-pre-wrap text-sm leading-relaxed font-normal">
                  <h2 className="text-base font-semibold mb-4" id="paper-title">{title}</h2>
                  {plainSummary}
                </article>
              )}
            </TabsContent>
            <TabsContent value="graph" className="w-full p-3 flex flex-col gap-3">
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <button
                  onClick={() => setCurrentSection('ALL')}
                  className={`px-2 py-1 rounded border text-xs ${currentSection==='ALL' ? 'bg-primary text-primary-foreground border-primary' : 'bg-background/60 hover:bg-background'} transition`}
                >All</button>
                {sectionsOverview.map(s => (
                  <button key={s.id} onClick={() => setCurrentSection(s.section)} className={`px-2 py-1 rounded border text-xs ${currentSection===s.section ? 'bg-primary text-primary-foreground border-primary' : 'bg-background/60 hover:bg-background'} transition`}>{s.section}</button>
                ))}
              </div>
              <div className="h-[70vh] relative border rounded bg-card overflow-hidden">
                <div ref={cyContainerRef} className="absolute inset-0" />
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
    </div>
  );
};
