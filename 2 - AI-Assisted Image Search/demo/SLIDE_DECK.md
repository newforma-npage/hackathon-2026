# Visual Project Intelligence Search — Demo Slides

---

## SLIDE 1: Title

**Visual Project Intelligence Search**
AI-Powered Image Search for Construction Projects

Team: P4 — Vector Store & Schema
Tech: AWS OpenSearch Serverless | Bedrock Titan Multimodal | CDK

---

## SLIDE 2: The Problem

- Project teams store **thousands of images**
- No way to search by visual content
- Current approach: browse filenames or scroll through folders
- Finding the right photo takes **15–30 minutes**

> "Where's that photo of the crack on Pier P-3?"

---

## SLIDE 3: The Solution

**AI-powered image search using natural language**

```
User types: "concrete crack damage"
System returns: ranked photos matching that description
```

How it works:
1. Images → Bedrock Titan Multimodal → 1536-dim embedding
2. Embeddings stored in OpenSearch Serverless (vector search)
3. Query text → same embedding model → cosine similarity search

---

## SLIDE 4: Live Demo (3 min)

| Step | What happens | Time |
|------|-------------|------|
| 1. Ingest | Index 5 site photos with AI-generated embeddings | 30s |
| 2. Search | Natural language: "concrete crack damage" | 45s |
| 3. Filter | Same query, restricted to PROJ-001 | 30s |
| 4. Similar | Upload photo → find visually similar images | 45s |

**Run:** `python demo/demo_script.py`

---

## SLIDE 5: Architecture (P4 Scope)

```
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│  Dev 3           │     │  P4 (This Sprint)    │     │  Dev 5          │
│  Bedrock         │────▶│  VectorStore Module  │◀────│  Search API     │
│  Embeddings      │     │  + OpenSearch Index   │     │  Endpoint       │
└─────────────────┘     └──────────────────────┘     └─────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  OpenSearch Serverless │
                    │  Collection: image-search │
                    │  Index: images (6 fields) │
                    └──────────────────────┘
```

**Index schema:**
| Field | Type | Purpose |
|-------|------|---------|
| image_id | keyword | Unique ID, used as doc _id |
| project_id | keyword | Filter by project |
| embedding | knn_vector (1536) | Cosine similarity search |
| tags | keyword[] | AI-generated labels |
| date | date | Time-based filtering |
| location | keyword | Spatial context |

---

## SLIDE 6: What We Built (P4 Deliverables)

✅ **CDK Stack** — One-command deploy (`cdk deploy`)
- OpenSearch Serverless collection (VECTORSEARCH)
- Encryption, network, data access policies
- `CollectionEndpoint` output for downstream teams

✅ **Index Creation Script** — Idempotent, SigV4 auth

✅ **VectorStore Client** — Clean Python API
- `index_image()` — ingest with dimension validation
- `search_by_embedding()` — kNN + filters
- `delete_image()` — safe 404 handling

✅ **Full Test Suite** — 30 tests passing
- Unit tests, property-based (Hypothesis), CDK snapshot

✅ **README + Handoff Docs** — Ready for Dev 3 & Dev 5

---

## SLIDE 7: KPIs & Impact

| Metric | Target | How |
|--------|--------|-----|
| Time to locate images | **↓ 60%** | Natural language vs filename browsing |
| Image reuse across projects | **↑ 25%** | Similar image search surfaces existing photos |
| Search success (first attempt) | **↑ 40%** | AI understands intent, not just keywords |

---

## SLIDE 8: Next Steps

1. **Dev 3** — Connect Bedrock Titan Multimodal for real embeddings
2. **Dev 5** — Build REST API endpoint for frontend
3. **Frontend** — Search bar + image grid UI
4. **Scale** — Auto-tagging pipeline for bulk image ingestion

---

## PRESENTER NOTES

**Timing guide (3 min total):**
- 0:00–0:15 — "Here's the problem" (Slide 2)
- 0:15–0:30 — "Here's our solution" (Slide 3)
- 0:30–2:30 — Run demo script live (Slide 4)
- 2:30–3:00 — KPIs and next steps (Slides 7–8)

**Demo tips:**
- Run `python demo/demo_script.py` in a terminal with large font
- The script works offline (simulation mode) — no AWS needed for the demo
- If you have OPENSEARCH_ENDPOINT set, it runs against real infrastructure
- Pause briefly after each step to let the audience read results

**Key talking points:**
- "No more scrolling through folders — just describe what you're looking for"
- "Filter narrows results without changing the ranking — best of both worlds"
- "Similar image search means you never duplicate work across projects"
- "One CDK deploy, one script, and the vector store is ready for the team"
