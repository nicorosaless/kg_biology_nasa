import React, { useCallback, useEffect, useRef, useState } from 'react';
import cytoscape, { Core } from 'cytoscape';

interface Phase5GraphProps {
  paperId: string;
  heightPx?: number; // optional explicit height fallback
}

interface Phase5Node {
  id: string | number;
  label: string;
  type?: string;
  freq?: number;
  nav?: { section?: string };
}

interface Phase5Edge {
  source: string | number;
  target: string | number;
  type?: string;
}

interface GraphPayload {
  paper_id: string;
  section?: string;
  nodes: Phase5Node[];
  edges: Phase5Edge[];
  n_nodes?: number;
  n_edges?: number;
}

const colorByType = (t?: string) => {
  switch (t) {
    case 'GENE_PRODUCT': return '#6366f1';
    case 'CHEMICAL': return '#f59e0b';
    case 'DISEASE': return '#ef4444';
    case 'PHENOTYPE': return '#10b981';
    case 'PATHWAY': return '#8b5cf6';
    case 'CELL_TYPE': return '#0ea5e9';
    default: return '#64748b';
  }
};

export const Phase5Graph = ({ paperId, heightPx = 640 }: Phase5GraphProps) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [mode, setMode] = useState<'overview' | 'section'>('overview');
  const [currentSection, setCurrentSection] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<string[]>([]); // stack of sections
  const [overviewCounts, setOverviewCounts] = useState<{nodes:number;edges:number}|null>(null);
  const [sections, setSections] = useState<{section:string; relations:number; page?:number|null}[]>([]);
  const [secError, setSecError] = useState<string|null>(null);
  const [hoverInfo, setHoverInfo] = useState<{x:number;y:number;label:string;type?:string;freq?:number;section?:string;sections?:string[]}|null>(null);
  const [sectionChoice, setSectionChoice] = useState<{label:string;sections:string[]}|null>(null);
  const [selectedNode, setSelectedNode] = useState<{id:string; label:string; type?:string; freq?:number; sections?:string[]; nav?:any} | null>(null);
  const visibilityCheckRef = useRef<number | null>(null);
  const [containerSize, setContainerSize] = useState<{w:number;h:number}>({w:0,h:0});

  const fetchGraph = async (section?: string) => {
    setLoading(true); setError(null);
    try {
      let url: string;
      if (!section) {
        url = `/api/paper/${paperId}/graph/overview`;
      } else {
        url = `/api/paper/${paperId}/graph/section/${encodeURIComponent(section)}`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data: GraphPayload = await res.json();
      drawGraph(data, section || null);
      if (!section) setOverviewCounts({nodes: data.n_nodes || data.nodes.length, edges: data.n_edges || data.edges.length});
    } catch (e: any) {
      setError(e.message || 'Error cargando grafo');
    } finally { setLoading(false); }
  };

  // Fetch section overview once (list for side navigation)
  const fetchSections = async () => {
    setSecError(null);
    try {
      const res = await fetch(`/api/paper/${paperId}/sections`);
      if (!res.ok) throw new Error('No sections');
      const data = await res.json();
      const secs = (data.sections || []).map((s:any)=> ({section: s.section, relations: s.relations, page: s.page}));
      setSections(secs);
    } catch (e:any) {
      setSecError(e.message || 'Error secciones');
    }
  };

  const drawGraph = (data: GraphPayload, section: string | null) => {
    setMode(section? 'section':'overview');
    setCurrentSection(section);
    const elements = [
      ...data.nodes.map(n => ({ data: { id: String(n.id), label: n.label, type: n.type || 'UNK', section: n.nav?.section, freq: n.freq, sections: (n as any).sections, nav: n.nav } })),
      ...data.edges.map(e => ({ data: { id: `${e.source}-${e.target}-${Math.random().toString(36).slice(2)}`, source: String(e.source), target: String(e.target) } }))
    ];
    if (cyRef.current) {
      cyRef.current.destroy();
      cyRef.current = null;
    }
    const cy = cytoscape({
      container: containerRef.current!,
      elements,
      style: [
        { selector: 'node', style: {
          label: 'data(label)',
          'font-size': '11px',
          'text-wrap': 'wrap',
          'text-max-width': '140px',
          'background-color': (ele: any)=> colorByType(ele.data('type')),
          width: (ele: any)=> 50 + (ele.degree()*2),
          height: (ele: any)=> 50 + (ele.degree()*2),
          color: '#fff',
          'border-width': 2,
          'border-color': '#1e293b'
        }},
        { selector: 'edge', style: {
          width: 2,
          'line-color': '#94a3b8',
          'curve-style': 'bezier',
          opacity: 0.55
        }},
        { selector: 'node:selected', style: {
          'border-color': '#f59e0b', 'border-width': 4
        }}
      ],
      wheelSensitivity: 0.2
    });
    cy.on('mouseover','node',(evt)=>{
      const n = evt.target;
      const bb = (evt as any).renderedPosition || n.renderedPosition();
      setHoverInfo({
        x: bb.x + 12,
        y: bb.y + 12,
        label: n.data('label'),
        type: n.data('type'),
        freq: n.data('freq'),
        section: n.data('section'),
        sections: n.data('sections')
      });
    });
    cy.on('mouseout','node',()=> setHoverInfo(null));
    cy.on('mousemove','node',(evt)=>{
      const rp = (evt as any).renderedPosition;
      if (hoverInfo && rp) setHoverInfo({...hoverInfo, x: rp.x + 12, y: rp.y + 12});
    });
    const inSection = !!section;
    cy.on('tap','node',(evt)=>{
      const node = evt.target;
      if (!inSection) {
        const sectionName = node.data('section');
        const allSections: string[] = node.data('sections') || (sectionName? [sectionName]: []);
        if (allSections.length <= 1) {
          if (sectionName) fetchGraph(sectionName);
        } else {
          setSectionChoice({label: node.data('label'), sections: allSections});
        }
        return;
      }
      // Section mode: open detail panel
      setSelectedNode({
        id: node.id(),
        label: node.data('label'),
        type: node.data('type'),
        freq: node.data('freq'),
        sections: node.data('sections'),
        nav: node.data('nav')
      });
      // debug
      try { console.debug('Node selected (section mode)', node.data()); } catch {}
    });
    // Breadcrumb double click in section -> back
    cyRef.current = cy;
    const layout = cy.layout({ name: 'cose', animate: false, fit: true, padding: 20 });
    layout.run();
    // After a tick, ensure proper sizing (if tab just became visible)
    requestAnimationFrame(()=> { cy.resize(); cy.fit(); });
  };

  useEffect(()=> { fetchGraph(); fetchSections(); /* eslint-disable-next-line */ }, [paperId]);

  const goBack = () => {
    if (mode==='section') {
      setSelectedNode(null);
      fetchGraph();
    }
  };

  // Resize observer / visibility polling to avoid blank canvas if size=0 at mount
  useEffect(()=> {
    const el = containerRef.current?.parentElement; // graph area div
    if (!el) return;
    const ro = new ResizeObserver(entries => {
      for (const e of entries) {
        const cr = e.contentRect;
        setContainerSize({w: cr.width, h: cr.height});
        if (cyRef.current) { cyRef.current.resize(); }
      }
    });
    ro.observe(el);
    // Poll a few frames until non-zero
    let attempts = 0;
    const poll = () => {
      attempts++;
      if (containerRef.current && containerRef.current.clientWidth > 10 && containerRef.current.clientHeight > 10) {
        if (cyRef.current) { cyRef.current.resize(); cyRef.current.fit(); }
        return;
      }
      if (attempts < 10) visibilityCheckRef.current = window.requestAnimationFrame(poll);
    };
    visibilityCheckRef.current = window.requestAnimationFrame(poll);
    return () => {
      if (visibilityCheckRef.current) cancelAnimationFrame(visibilityCheckRef.current);
      ro.disconnect();
    };
  }, [paperId]);

  return (
    <div className='w-full flex flex-col relative' style={{height: heightPx}}>
      {/* Header */}
      <div className='flex items-center gap-2 p-2 border-b border-slate-700 bg-slate-900/60 text-xs text-slate-200'>
        {mode==='section' && (
          <button onClick={goBack} className='px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 transition'>← Overview</button>
        )}
        <span className='font-semibold'>{mode==='overview'? 'Overview Graph':'Section: '+currentSection}</span>
        {mode==='section' && currentSection && (
          (()=>{ const sec = sections.find(s=> s.section===currentSection); if(!sec) return null; const page=sec.page; return (
            <button
              onClick={()=> { if(page){ window.dispatchEvent(new CustomEvent('phase5:locate-pdf', { detail: { paperId, section: currentSection, page } })); } }}
              disabled={!page}
              className='ml-3 px-2 py-1 rounded bg-indigo-600 disabled:opacity-40 hover:bg-indigo-500 text-white text-[11px] whitespace-nowrap'
              title={page? `Page ${page}`: 'No page info'}
            >View section in PDF{page? ` (p${page})`: ''}</button>
          ); })()
        )}
        {mode==='overview' && overviewCounts && !loading && !error && (
          <span className='ml-2 text-slate-400'>{overviewCounts.nodes} nodos · {overviewCounts.edges} aristas</span>
        )}
        {loading && <span className='ml-2 animate-pulse text-amber-400'>cargando…</span>}
        {error && <span className='ml-2 text-red-400'>{error}</span>}
      </div>
      {/* Body */}
      <div className='flex flex-1 overflow-hidden'>
        <div className='w-56 border-r border-slate-800 bg-slate-900/40 overflow-y-auto text-[11px] p-2 space-y-1'>
          <div className='font-semibold text-slate-300 mb-1'>Secciones</div>
          {secError && <div className='text-red-400'>{secError}</div>}
          {!secError && sections.length===0 && <div className='text-slate-500'>—</div>}
          {sections.map(s => (
            <div key={s.section} className='space-y-0.5'>
              <button disabled={mode==='section' && currentSection===s.section} onClick={()=> fetchGraph(s.section)}
                className={`w-full text-left px-2 py-1 rounded hover:bg-slate-700/50 transition ${(currentSection===s.section)?'bg-slate-700/60':''}`}>
                <span className='block truncate'>{s.section}</span>
                <span className='text-slate-500 text-[10px]'>{s.relations} rels · p{s.page||'?'}</span>
              </button>
            </div>
          ))}
        </div>
        <div className='flex-1 relative bg-slate-950'>
          <div ref={containerRef} className='absolute inset-0' />
          {!loading && !error && cyRef.current && cyRef.current.nodes().length===0 && (
            <div className='absolute inset-0 flex items-center justify-center text-slate-400 text-sm'>Sin nodos</div>
          )}
          {!loading && !error && cyRef.current && (containerSize.w < 20 || containerSize.h < 20) && (
            <div className='absolute inset-0 flex items-center justify-center text-amber-400 text-[11px]'>Contenedor sin tamaño — revisa estilos/tab</div>
          )}
        </div>
        {mode==='section' && selectedNode && (
          <div className='w-64 border-l border-slate-800 bg-slate-900/60 flex flex-col text-[11px] p-3 gap-2'>
            <div className='font-semibold text-slate-200 leading-snug break-words'>{selectedNode.label}</div>
            {selectedNode.type && <div className='text-slate-400'>Tipo: <span className='text-slate-200'>{selectedNode.type}</span></div>}
            {selectedNode.freq!=null && <div className='text-slate-400'>Frecuencia: <span className='text-slate-200'>{selectedNode.freq}</span></div>}
            {selectedNode.sections && selectedNode.sections.length>0 && (
              <div className='text-slate-400'>Secciones:
                <ul className='mt-1 space-y-0.5 max-h-32 overflow-auto'>
                  {selectedNode.sections.map(s=> <li key={s} className='text-slate-300 truncate'>{s}</li>)}
                </ul>
              </div>
            )}
            {/* Node-level PDF navigation removed; navigation now at section level */}
            <button onClick={()=> setSelectedNode(null)} className='px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-[11px]'>Cerrar</button>
          </div>
        )}
      </div>
      <div className='absolute bottom-2 right-2 text-[10px] text-slate-500'>
        {mode==='overview'? 'Click nodo → subgrafo' : 'Click nodo → panel detalle'}
      </div>
      {hoverInfo && (
        <div className='pointer-events-none absolute z-30 px-2 py-1 rounded bg-black/80 text-[10px] leading-tight text-white border border-white/10 shadow'
          style={{left: hoverInfo.x, top: hoverInfo.y}}>
          <div className='font-semibold'>{hoverInfo.label}</div>
          {hoverInfo.type && <div className='opacity-80'>Tipo: {hoverInfo.type}</div>}
          {hoverInfo.freq!=null && <div className='opacity-60'>Freq: {hoverInfo.freq}</div>}
          {hoverInfo.section && <div className='opacity-60 truncate max-w-[180px]'>Sec: {hoverInfo.section}</div>}
          {hoverInfo.sections && hoverInfo.sections.length>1 && <div className='opacity-50'>{hoverInfo.sections.length} secciones</div>}
        </div>
      )}
      {sectionChoice && (
        <div className='absolute inset-0 z-40 flex items-center justify-center bg-black/50 backdrop-blur-sm'>
          <div className='bg-slate-900 border border-slate-700 rounded-lg p-4 w-72 max-h-[70vh] flex flex-col gap-3'>
            <div className='text-sm font-semibold text-slate-200'>Selecciona sección</div>
            <div className='text-xs text-slate-400'>{sectionChoice.label}</div>
            <div className='flex-1 overflow-auto space-y-1'>
              {sectionChoice.sections.map(s=> (
                <button key={s} onClick={()=> {fetchGraph(s); setSectionChoice(null);}} className='w-full text-left px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-[11px]'>
                  {s}
                </button>
              ))}
            </div>
            <button onClick={()=> setSectionChoice(null)} className='text-xs px-2 py-1 rounded bg-slate-700 hover:bg-slate-600'>Cancelar</button>
          </div>
        </div>
      )}
    </div>
  );
};
