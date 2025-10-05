<div align="center">

# CooperGraph: NASA Space Biology Knowledge Graph & Voice Agent

Explorable, conversational knowledge graph of 600+ NASA Space Biology open-access publications.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![Frontend](https://img.shields.io/badge/Frontend-React%20%2B%20D3-orange.svg)
[![Demo](https://img.shields.io/badge/Demo-YouTube-red.svg)](https://youtu.be/MUodpz5bQ00)

[🎥 Demo Video](https://youtu.be/MUodpz5bQ00) · [🔗 Repository](https://github.com/nicorosaless/kg_biology_nasa)

</div>

---

## 🛰️ Summary
CooperGraph is an interactive knowledge graph dashboard with an AI-powered conversational voice agent that turns NASA's 600+ space biology publications into a navigable research atlas. Users visually explore a force-directed graph, filter by mission (ISS, Shuttle, etc.), search, receive hybrid AI recommendations, and uniquely, control the entire system via natural voice commands (find, open, explain papers, navigate clusters). The platform accelerates discovery of research trends, knowledge gaps, and cross-domain links for scientists, mission planners, and research managers.

---

## ✨ Key Features
| Category | Highlights |
|----------|------------|
| Graph Exploration | Force-directed D3 visualization, cluster highlighting, mission & keyword filters |
| Hybrid Recommendations | Cluster-based + mission-based + content similarity for diverse discovery |
| Voice Navigation | Hands-free querying, opening, summarizing, and contextual exploration |
| Intelligent Search | TF‑IDF keyword extraction + semantic clustering |
| Mission Filtering | Explore publications by platform (ISS, Shuttle, etc.) |
| Topic Discovery | K-Means thematic clusters, gap spotting, related paper surfacing |
| Multimodal Interaction | Switch seamlessly between graph clicks, text search, and voice commands |
| Accessibility | Voice agent enables use in lab / presentation / low-vision contexts |

---

## 🧠 Recommendation & Clustering Approach
1. Text preprocessing (tokenization, normalization, stopword filtering)
2. TF-IDF vectorization of abstracts / key sections
3. K-Means clustering to derive thematic groups
4. Graph edges built from similarity thresholds + shared mission tags + inferred relations
5. Hybrid recommender:
   - Intra-cluster similarity
   - Cross-cluster diversity heuristic (circular rotation strategy)
   - Mission-aligned boosts
   - Content-based cosine similarity re-ranking

---

## 🗣️ Voice Agent (ElevenLabs Integration)
Supported intents (examples):
- "Find papers about muscle atrophy"
- "Open paper PMC5666799"
- "Explain this study"
- "Show related papers"
- "Navigate to the cluster about microgravity immune response"
- "Summarize the selected publication"

Pipeline:
1. User speech → ElevenLabs ASR
2. NLU intent parsing → internal action map
3. Backend query (graph / search / recommend)
4. Text synthesis (contextual explanation)
5. ElevenLabs TTS → audio playback

Attribution: All AI‑generated voice/audio content acknowledges model usage in UI logs.

---

## 🏗️ Architecture Overview
```
                     ┌────────────────────────┐
                     │  Voice Agent (UI)      │
                     │  Mic / Audio Player    │
                     └──────────┬─────────────┘
                                │ (WebSocket/HTTP)
                     ┌──────────▼─────────────┐
Frontend (React + D3)│  REST API Gateway      │  Flask Backend (Python)
 Graph, Filters, UI  │  /api/... endpoints    │  ┌───────────────────────────┐
──────────┬──────────┘                        │  │ NLP Pipeline               │
          │ Data (JSON)                       │  │  - TF-IDF / K-Means        │
          │                                   │  │  - Graph Build (NetworkX)  │
          │                                   │  │  - Recommendations         │
          │                                   │  └──────────┬────────────────┘
          │                                   │             │
          │                                   │   Structured Graph Data
          │                                   │ (nodes, edges, clusters, meta)
          │                                   │
          ▼                                   │
   D3 Force Graph                             │
                                              │
                                      Data Pipeline Scripts
                                      (parsing → extraction → clustering → graph JSON)
```

---

## 🧩 Tech Stack
| Layer | Technologies |
|-------|--------------|
| Frontend | React, TypeScript, Vite, D3.js, TailwindCSS |
| Backend | Python, Flask (API) |
| Data Processing | pandas, scikit-learn, NetworkX |
| Voice | ElevenLabs APIs (ASR + TTS) |
| Storage / Files | CSV / JSON artifacts (graph, clusters) |
| Tooling | GitHub, (optional) Git LFS for large PDFs |

---

## 📂 Repository Structure (excerpt)
```
backend/
  api.py                # Flask endpoints
  full_pipeline.py      # End-to-end data/graph generation
  kg_creator/           # Phased graph construction modules
frontend/
  src/                  # React + D3 visualization
processed_grobid_pdfs/  # Parsed publication text (now versioned)
backend/SB_publications/pdfs/  # Source PDFs (now versioned; consider LFS)
output/                 # Generated summaries, status JSONs
neo4j_export/           # Cypher export artifacts
```

---

## 🔄 Data / Graph Generation Pipeline
Phased approach (see `backend/kg_creator/`):
1. Phase 1 – Parsing (`phase1_parse.py`): Extract structured text from PDFs (GROBID output)  
2. Phase 2 – Sentence Segmentation (`phase2_sentences.py`)  
3. Phase 3 – Entity Extraction (`phase3_entities.py`)  
4. Phase 4 – Relation Extraction (`phase4_relations.py`)  
5. Phase 5 – Graph Assembly (`phase5_graph.py`) → Nodes/Edges JSON  
6. Recommendation & Metadata Enrichment (`normalization.py`, `relation_rules.py`)  

`full_pipeline.py` orchestrates these steps.  

---

## 🚀 Quick Start
### 1. Clone
```bash
git clone https://github.com/nicorosaless/kg_biology_nasa.git
cd kg_biology_nasa
```

### 2. Backend Setup
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
export FLASK_ENV=development
python backend/api.py
```
API defaults to `http://localhost:8000` (adjust if different inside `api.py`).

### 3. Frontend Setup
```bash
cd frontend
npm install   # or bun/pnpm/yarn
npm run dev
```
Open the served URL (typically `http://localhost:5173`).

### 4. (Optional) Run Full Data Pipeline
```bash
python backend/full_pipeline.py --rebuild-all
```

### 5. Voice Agent
Configure ElevenLabs API key (e.g. `.env`):
```
ELEVENLABS_API_KEY=your_key_here
```
Start the voice agent runner (example script under `backend/VoiceAgent/`).

---

## 🔌 Example API Endpoints
| Endpoint | Description |
|----------|-------------|
| `/api/paper/<pmcid>/graph/overview` | Basic node/edge stats for paper subgraph |
| `/api/paper/<pmcid>/sections` | Section metadata |
| `/api/paper/<pmcid>/graph/section/<SECTION>` | Section-level subgraph |
| `/api/recommend/<pmcid>` | Recommended related papers (if implemented) |
| `/api/search?q=term` | Keyword / content search |

> Explore `api.py` for the authoritative and current list.

---

## 🤖 AI & ML Usage (Transparency)
| Component | AI / Algorithm | Purpose |
|-----------|----------------|---------|
| Clustering | K-Means (scikit-learn) | Thematic grouping |
| Text Features | TF-IDF Vectorizer | Keyword weighting & similarity |
| Graph Logic | Cosine similarity + heuristic link rules | Edge creation |
| Voice Agent | ElevenLabs ASR + TTS | Speech in/out |

All AI-assisted code was reviewed, tested, and adapted by maintainers. Comments & docs acknowledge assistance where relevant.

---

## 🛰️ Data Source
NASA Space Biology open-access publications (608 full-text items). Ensure compliance with NASA open data licensing and attribution norms when redistributing derived artifacts.

---

## 📏 Design Principles
- Accessibility-first (voice + visual)
- Multimodal exploration
- Extensible pipeline stages
- Performance-aware graph updates
- Transparent AI usage & reproducibility

---

## 🧪 Testing & Reproducibility
Recommendations:
- Freeze Python deps with `pip freeze > requirements.lock`
- Use deterministic seeds for clustering (e.g. `KMeans(random_state=42)`).
- Provide snapshot of generated graph JSON in `output/` for baseline comparisons.

---

## 📦 Large Files & PDFs
Now versioning:
- `processed_grobid_pdfs/`
- `backend/SB_publications/pdfs/`

Consider enabling Git LFS for PDF + large JSON artifacts:
```bash
git lfs install
git lfs track "*.pdf"
git add .gitattributes
git commit -m "Enable LFS for PDFs"
```

### 📥 PDF Download / Redownload
The repository includes a robust downloader at `backend/SB_publications/download_pdfs.py` for retrieving (or reconstructing) the NASA Space Biology PMC PDFs. You can safely remove local PDFs later and regenerate them using this script.

Key behaviors:
- Reads master CSV: `backend/SB_publications/SB_publication_PMC.csv`
- (Default) Filters to a target macro-cluster (Radiation & Shielding: `C103`) using `frontend/public/data/csvGraph.json`
- Cleans (deletes) any PDFs not belonging to that cluster when filtering is enabled
- Attempts multiple sources: NCBI EFetch → Europe PMC → direct article parsing (with fallbacks for dynamic pages / POW)
- Skips already-downloaded PDFs larger than a small size threshold

Usage examples (from repository root):
```bash
# 0) Activate environment
source .venv/bin/activate

# 1) Download ONLY cluster C103 (default behavior, all PMCs in cluster)
python backend/SB_publications/download_pdfs.py

# 2) Download all PMCs (disable cluster filter)
python -c "import backend.SB_publications.download_pdfs as d; d.main(limit=None, enforce_cluster=False)"

# 3) Limit to first 10 PMCs (for quick test)
python -c "import backend.SB_publications.download_pdfs as d; d.main(limit=10, enforce_cluster=True)"

# 4) Custom output directory
export PDF_OUTPUT_DIR=/path/to/my_pdfs
python backend/SB_publications/download_pdfs.py
```

Parameters (inside `main(limit=None, enforce_cluster=True)`):
- `limit`: `None` processes all rows; set an integer for quick sampling.
- `enforce_cluster`: when `True`, only keeps/downloads PMCs in cluster `C103` and removes outsiders.

Regenerating cluster filter:
If you re-run the graph pipeline and cluster IDs change, ensure `csvGraph.json` is updated (see pipeline section) before downloading.

Safety tip:
If you are about to delete local PDFs after pushing to GitHub, you can always re-create them with these commands later.


---

## 🗺️ Roadmap
- [ ] Enhanced semantic search (embedding-based)
- [ ] Advanced relation extraction (dependency / transformer models)
- [ ] Temporal evolution visualization
- [ ] Fine-grained voice intents (compare papers, cluster summaries)
- [ ] Export to Neo4j live instance
- [ ] Progressive graph streaming for very large corpora

---

## 🤝 Contributing
1. Fork repo
2. Create feature branch: `git checkout -b feature/awesome`
3. Commit changes (`git commit -m "Add awesome"`)
4. Push branch (`git push origin feature/awesome`)
5. Open Pull Request

Please include: rationale, screenshots (if UI), and performance considerations for graph-scale changes.

---

## 📜 License
Released under the MIT License. See `LICENSE` for full text.

Third-party components:
- GROBID (AGPL / mixed licensing) included under `backend/grobid/` – respect its upstream license terms
- pdf.js (Mozilla Public License) licenses retained in subdirectories
- ElevenLabs APIs (proprietary service) – requires valid API key and compliance with their ToS

If you redistribute builds including these components, ensure all original notices remain intact.

---

## 🧾 Citation (Suggested Format)
If you use CooperGraph in academic work:
```
@misc{coopergraph2025,
  title        = {CooperGraph: Conversational Knowledge Graph for NASA Space Biology Publications},
  author       = {Rosales, N. and Contributors},
  year         = {2025},
  url          = {https://github.com/nicorosaless/kg_biology_nasa},
  note         = {Accessed: YYYY-MM-DD}
}
```

---

## 🙌 Acknowledgments
- NASA Space Biology Open Access corpus
- ElevenLabs for voice technologies
- Open-source community (scikit-learn, NetworkX, D3, Flask, React)
- GitHub Copilot for assisted development

---

## 📬 Contact
Questions / suggestions: open an Issue or submit a Discussion in the repository.

---

Enjoy exploring space biology knowledge—by click, by query, or by voice. 🚀
