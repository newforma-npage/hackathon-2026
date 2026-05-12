# Embedding & Vector Store Schema

## Bedrock Models

| Purpose | Model ID | Output Dimensions |
|---|---|---|
| Image embedding (ingest) | `amazon.titan-embed-image-v1` | **1024** |
| Image + text (multimodal) | `amazon.titan-embed-image-v1` | **1024** |
| Text query embedding | `amazon.titan-embed-text-v2:0` | **1536** |

> The vector index stores **1024-dim multimodal vectors** (image embeddings).  
> Text queries are embedded with the 1536-dim text model; cosine similarity handles the cross-modal comparison because both models share a compatible semantic space.

---

## Vector Index Schema

### OpenSearch (primary)

Index name: `visual-project-intelligence` (override with `VECTOR_INDEX_NAME` env var)

```json
{
  "settings": {
    "index.knn": true,
    "index.knn.algo_param.ef_search": 512
  },
  "mappings": {
    "properties": {
      "embedding":       { "type": "knn_vector", "dimension": 1024,
                           "method": { "name": "hnsw", "engine": "nmslib",
                                       "space_type": "cosinesimil",
                                       "parameters": { "ef_construction": 512, "m": 16 } } },
      "photo_id":        { "type": "keyword" },
      "project_id":      { "type": "keyword" },
      "project_name":    { "type": "text" },
      "filename":        { "type": "keyword" },
      "date_taken":      { "type": "date" },
      "location":        { "type": "text" },
      "taken_by":        { "type": "keyword", "index": false },
      "ai_labels":       { "type": "keyword" },
      "ai_description":  { "type": "text" },
      "index_version":   { "type": "integer" },
      "indexed_at":      { "type": "date" }
    }
  }
}
```

### pgvector (alternate)

Table: `photo_embeddings`

```sql
CREATE TABLE photo_embeddings (
    photo_id        TEXT PRIMARY KEY,
    embedding       VECTOR(1024) NOT NULL,   -- Titan Multimodal v1
    project_id      TEXT NOT NULL,
    project_name    TEXT,
    filename        TEXT NOT NULL,
    date_taken      TIMESTAMPTZ,
    location        TEXT,
    taken_by        TEXT,
    ai_labels       TEXT[] DEFAULT '{}',
    ai_description  TEXT,
    index_version   INTEGER NOT NULL DEFAULT 1,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index (cosine distance)
CREATE INDEX photo_embeddings_hnsw_idx
    ON photo_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

---

## PhotoVector Record

```
photo_id        string   UUID (deterministic from filename if not set)
embedding       float[]  1024 floats — Titan Multimodal image embedding
project_id      string   e.g. "PROJ-001"
project_name    string   e.g. "Harbor Bridge Reconstruction"
filename        string   e.g. "site-photo-01.jpg"
date_taken      datetime ISO 8601
location        string   site location description
taken_by        string   photographer name (not indexed)
ai_labels       string[] Rekognition label names, lowercased, confidence ≥ 70%
ai_description  string   top-8 Rekognition labels joined as natural language
index_version   int      1 = Titan Multimodal v1
indexed_at      datetime UTC timestamp of indexing
```

---

## Ingestion Pipeline

```
S3 / local file
    │
    ├─► Rekognition DetectLabels (minConfidence=70)
    │       → ai_labels[], ai_description
    │
    ├─► Bedrock titan-embed-image-v1
    │       → embedding[1024]
    │
    └─► VectorStore.upsert(PhotoVector)
        MetadataDB.upsert(EnrichedPhoto)
```

## Query Pipeline

```
Text query "foundation cracks"
    │
    ├─► Bedrock titan-embed-text-v2:0
    │       → queryVector[1536]
    │
    └─► VectorStore.knnSearch(queryVector, k=50, filters)
            → [{photo_id, cosine_score}]
            → fetch metadata → rank → paginate → return
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `AWS_REGION` | `us-east-1` | AWS region for Bedrock + Rekognition |
| `VECTOR_BACKEND` | `opensearch` | `opensearch` or `pgvector` |
| `OPENSEARCH_HOST` | — | OpenSearch domain endpoint |
| `OPENSEARCH_USER` | — | HTTP basic auth username (optional) |
| `OPENSEARCH_PASS` | — | HTTP basic auth password (optional) |
| `VECTOR_INDEX_NAME` | `visual-project-intelligence` | Index / table name |
| `PGVECTOR_DSN` | — | PostgreSQL connection string (pgvector only) |
