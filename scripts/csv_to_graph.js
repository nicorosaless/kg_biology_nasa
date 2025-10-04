// Convert SB_publication_PMC.csv -> GraphData JSON matching webapp/public/data/mockGraph.json
// Usage (from repo root): node scripts/csv_to_graph.js
// Output: webapp/public/data/csvGraph.json

const fs = require('fs');
const path = require('path');

const CSV_PATH = path.join(process.cwd(), 'ElevenLabs', 'SB_publication_PMC.csv');
const OUT_PATH = path.join(process.cwd(), 'webapp', 'public', 'data', 'csvGraph.json');

// Simple CSV parser for two columns: Title,Link; handles quoted titles with commas
function parseCSV(text) {
  const lines = text.split(/\r?\n/).filter(Boolean);
  // drop header if matches
  if (lines.length && /^\s*Title\s*,\s*Link\s*$/i.test(lines[0])) {
    lines.shift();
  }
  const rows = [];
  for (const line of lines) {
    // parse with state machine for quotes
    let inQuotes = false;
    let field = '';
    const fields = [];
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (ch === '"') {
        if (inQuotes && line[i + 1] === '"') {
          // escaped double quote
          field += '"';
          i++;
        } else {
          inQuotes = !inQuotes;
        }
      } else if (ch === ',' && !inQuotes) {
        fields.push(field);
        field = '';
      } else {
        field += ch;
      }
    }
    fields.push(field);
    if (fields.length >= 2) {
      rows.push({ title: fields[0].trim(), link: fields[1].trim() });
    }
  }
  return rows;
}

function extractPMC(link) {
  // Expect like: https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4136787/
  const m = link.match(/\/PMC(\d+)\/?$/) || link.match(/\/PMC(\d+)\//);
  if (m) return `PMC${m[1]}`;
  // fallback: last token without slash
  const parts = link.replace(/\/$/, '').split('/');
  return parts[parts.length - 1] || `ID${Math.random().toString(36).slice(2, 8)}`;
}

function hashToClusterIndex(title, total = 4) {
  // Stable pseudo-hash to 0..total-1
  let h = 0;
  for (let i = 0; i < title.length; i++) h = (h * 31 + title.charCodeAt(i)) >>> 0;
  return h % total;
}

function buildGraph(rows) {
  // Define 12 macroclusters for improved legibility
  const clusterDefs = [
    ['C101', 'Space Plant Systems', 'Plant growth, gene expression, and bioproduction in space habitats'],
    ['C102', 'Human Health & Performance', 'Physiology, countermeasures, and health monitoring for astronauts'],
    ['C103', 'Radiation & Shielding', 'Biological effects of space radiation and protection strategies'],
    ['C104', 'Bio-regenerative Life Support', 'Microbial-plant systems and resource cycling for long-duration missions'],
    ['C105', 'Microbiome & Host Response', 'Host–microbe interactions and habitat microbiomes in space'],
    ['C106', 'Neuroscience & Behavior', 'Neural development, function, and adaptation in altered gravity'],
    ['C107', 'Musculoskeletal & Bone', 'Bone density, muscle atrophy, and mechanobiology'],
    ['C108', 'Immunology & Infection', 'Immune responses and pathogen behavior in space'],
    ['C109', 'Omics & Data Systems', 'Multi-omics pipelines, FAIR data, and platforms (GeneLab)'],
    ['C110', 'Methods & Instrumentation', 'Flight hardware, assays, and protocols for space biology'],
    ['C111', 'Microbial Biotech', 'Microbial engineering, biofilms, and applications off-Earth'],
    ['C112', 'Development & Reproduction', 'Developmental biology, reproduction, and stem cells']
  ];

  const missions = ['ISS', 'Mars', 'Moon'];
  const clusters = clusterDefs.map((c, i) => ({
    id: c[0],
    label: `Macrocluster: ${c[1]}`,
    count: 0,
    mission: missions[i % missions.length],
    description: c[2]
  }));

  const papers = [];
  const edges = [];

  rows.forEach((row, idx) => {
    const pmc = extractPMC(row.link);
    const cIdx = hashToClusterIndex(row.title, clusters.length);
    const clusterId = clusters[cIdx].id;
    const year = 2010 + (idx % 16); // pseudo year distribution 2010-2025
    const mission = clusters[cIdx].mission;

    const topics = [];
    // naive topics from title keywords
    row.title.replace(/[\"\.:;,()\[\]\-]/g, ' ').split(/\s+/).filter(Boolean).slice(0, 6).forEach(w => {
      const t = w.replace(/^[A-Z]/, c => c).trim();
      if (t && !/https?:/i.test(t)) topics.push(t);
    });
    while (topics.length < 4) topics.push('Topic ' + (topics.length + 1));

    papers.push({
      id: pmc,
      clusterId,
      label: row.title,
      topics: topics.slice(0, 4),
      year,
      mission,
      gapScore: Math.round(((idx % 100) / 100) * 100) / 100,
      summary: `From ${pmc}: ${row.title}`
    });
    clusters[cIdx].count += 1;

    // create a light edge to previous in same cluster to give some structure
    const prevInCluster = papers.findLast?.(p => p.clusterId === clusterId && p.id !== pmc);
    if (prevInCluster) {
      edges.push({ source: prevInCluster.id, target: pmc, weight: 0.4 + (idx % 20) / 100 });
    }
  });

  // Add a few cross-cluster edges by sampling every Nth paper
  for (let i = 0; i < papers.length - 6; i += 11) {
    const a = papers[i];
    const b = papers[i + 6];
    if (a && b && a.clusterId !== b.clusterId) {
      edges.push({ source: a.id, target: b.id, weight: 0.25 + (i % 10) / 100 });
    }
  }

  return { clusters, papers, edges };
}

function main() {
  const csv = fs.readFileSync(CSV_PATH, 'utf8');
  const rows = parseCSV(csv).filter(r => r.title && r.link);
  const graph = buildGraph(rows);
  fs.mkdirSync(path.dirname(OUT_PATH), { recursive: true });
  fs.writeFileSync(OUT_PATH, JSON.stringify(graph, null, 2), 'utf8');
  console.log(`Wrote ${graph.papers.length} papers into ${OUT_PATH}`);
}

if (require.main === module) {
  main();
}
