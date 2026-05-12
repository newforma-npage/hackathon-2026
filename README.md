# Visual Project Intelligence Search

AI-powered image search for construction project teams. Uses AWS Rekognition and Bedrock to automatically tag and index site photos, then lets users find them with natural language queries like "foundation cracks" or "steel beam connection" — no more hunting by filename.

---

## How it works

```
S3 upload
    │
    ├─► Lambda (image_ingestion)
    │       Extracts project_id, filename, timestamp
    │       Writes metadata record to DynamoDB (ai_indexed=False)
    │
    └─► FastAPI /api/photos/{filename}/ingest
            Rekognition → AI labels
            Bedrock Titan Multimodal → 1024-dim image embedding
            Upserts into vector store (OpenSearch or pgvector)
            Flips DynamoDB ai_indexed=True

User search query
    │
    └─► FastAPI /api/search
            Bedrock Titan Text v2 → 1536-dim text embedding
            kNN search in vector store
            Returns ranked results with project context
```

---

## Project structure

```
2 - AI-Assisted Image Search/
├── app/
│   ├── backend/
│   │   ├── main.py           # FastAPI app — search, ingest, similarity endpoints
│   │   ├── embeddings.py     # Bedrock Titan Multimodal + Text embedding client
│   │   └── vector_store.py   # OpenSearch k-NN and pgvector abstractions
│   ├── frontend/
│   │   └── index.html        # Search UI
│   ├── EMBEDDING_SCHEMA.md   # Vector index schema and model reference
│   └── requirements.txt
├── infra/
│   ├── app.py                # CDK app entry point
│   ├── cdk.json
│   ├── requirements.txt
│   └── stacks/
│       └── image_ingestion_stack.py  # S3 + DynamoDB + Lambda + event notifications
├── lambda/
│   └── image_ingestion/
│       ├── handler.py        # Lambda handler: S3 event → DynamoDB metadata
│       └── tests/
│           └── test_handler.py
└── Sample input data/
    ├── photo-metadata.json   # Project metadata for 16 sample photos
    └── site-photo-*.jpg      # Sample site photos (PROJ-001 through PROJ-008)
```

---

## Prerequisites

- Python 3.12+
- AWS CLI configured with credentials
- Node.js (for CDK CLI): `npm install -g aws-cdk`
- `uv` or `pip` for Python deps

---

## Running the FastAPI app

```bash
cd "2 - AI-Assisted Image Search/app"
pip install -r requirements.txt

# OpenSearch (default)
export VECTOR_BACKEND=opensearch
export OPENSEARCH_HOST=https://your-opensearch-endpoint
export AWS_REGION=us-east-1

# Or pgvector
export VECTOR_BACKEND=pgvector
export PGVECTOR_DSN=postgresql://user:pass@host:5432/dbname

uvicorn backend.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

### Key endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/photos` | List all photos with metadata |
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/photos/{filename}/ingest` | Run Rekognition + Bedrock on one photo |
| `POST` | `/api/photos/ingest-all` | Ingest all un-indexed photos |
| `POST` | `/api/search` | Natural language search |
| `POST` | `/api/search/similarity` | Upload image → find visually similar photos |
| `POST` | `/api/vector-store/init` | Create vector index / table |

---

## Deploying the Lambda + infrastructure

```bash
cd "2 - AI-Assisted Image Search/infra"
pip install -r requirements.txt

# First time only
cdk bootstrap

cdk deploy
```

This creates:
- S3 bucket for project images (key structure: `{project_id}/{filename}`)
- DynamoDB table `visual-project-photo-metadata` (PK: `project_id`, SK: `image_path`)
- Lambda function triggered on S3 ObjectCreated for `.jpg`, `.jpeg`, `.png`, `.tif`, `.tiff`

Set the `PHOTO_TABLE_NAME` env var in the FastAPI app to the deployed table name so it can flip `ai_indexed=True` after enrichment.

---

## Running the tests

```bash
# Using uvx (no separate install needed)
uvx --with pytest --with "moto[dynamodb]" --with boto3 \
    pytest "lambda/image_ingestion/tests" -v

# Or with pip
pip install pytest "moto[dynamodb]" boto3
pytest lambda/image_ingestion/tests -v
```

12 tests covering key parsing, record building, DynamoDB writes, URL decoding, batch processing, and idempotency.

---

## Embedding models

| Use | Model | Dimensions |
|-----|-------|-----------|
| Image ingestion | `amazon.titan-embed-image-v1` | 1024 |
| Text search query | `amazon.titan-embed-text-v2:0` | 1536 |

See `app/EMBEDDING_SCHEMA.md` for full vector index schema.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | AWS region |
| `VECTOR_BACKEND` | `opensearch` | `opensearch` or `pgvector` |
| `OPENSEARCH_HOST` | — | OpenSearch domain endpoint |
| `OPENSEARCH_USER` | — | Basic auth username (optional) |
| `OPENSEARCH_PASS` | — | Basic auth password (optional) |
| `VECTOR_INDEX_NAME` | `visual-project-intelligence` | Index / table name |
| `PGVECTOR_DSN` | — | PostgreSQL DSN (pgvector only) |
| `PHOTO_TABLE_NAME` | — | DynamoDB table name (from CDK deploy) |
