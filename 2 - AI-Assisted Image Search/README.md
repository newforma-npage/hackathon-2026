# Vector Store Setup — AI-Assisted Image Search

This component provisions the OpenSearch Serverless vector store used by the Visual Project Intelligence Search system. It covers infrastructure deployment, index creation, and the Python client module consumed by downstream developers.

---

## Prerequisites

Before you begin, make sure the following are installed and configured:

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Required for `vector_store.py` and scripts |
| AWS CDK | v2 (`aws-cdk-lib>=2.0.0`) | Install via `npm install -g aws-cdk` |
| boto3 | Latest | `pip install boto3` |
| opensearch-py | Latest | `pip install opensearch-py` |
| AWS credentials | — | Must have AOSS permissions (see below) |

### Required AWS Permissions

Your IAM identity (user or role) needs the following permissions on the OpenSearch Serverless collection:

- `aoss:CreateCollection`
- `aoss:CreateSecurityPolicy`
- `aoss:CreateAccessPolicy`
- `aoss:APIAccessAll` (for data plane operations: index, search, delete)

The CDK stack grants `aoss:*` on all indexes in the collection to the deploying account root and any optional application role you specify.

### Install Python dependencies

```bash
pip install boto3 opensearch-py
```

### Install CDK dependencies

```bash
cd cdk
pip install -r requirements.txt
```

---

## CDK Deployment

### 1. Bootstrap your AWS environment (first time only)

```bash
cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
```

### 2. Deploy the stack

```bash
cd cdk
cdk deploy
```

To also grant an application role access to the collection, pass it as CDK context:

```bash
cdk deploy --context app_role_arn=arn:aws:iam::123456789012:role/MyAppRole
```

### 3. Capture the `CollectionEndpoint` output

After a successful deploy, CDK prints the stack outputs. Copy the `CollectionEndpoint` value — you will need it for the next step.

```
Outputs:
ImageSearchStack.CollectionEndpoint = https://<collection-id>.us-east-1.aoss.amazonaws.com
```

This value is also available in the AWS Console under **CloudFormation → ImageSearchStack → Outputs → CollectionEndpoint**.

---

## Index Creation

Once the collection is deployed, create the `images` index with the required field mapping.

### 1. Set the endpoint environment variable

```bash
export OPENSEARCH_ENDPOINT=https://<collection-id>.us-east-1.aoss.amazonaws.com
```

### 2. Run the index creation script

```bash
python scripts/create_index.py
```

The script is idempotent — if the index already exists it logs `"Index 'images' already exists, skipping creation."` and exits cleanly.

You can also pass the endpoint directly as a CLI argument instead of using the environment variable:

```bash
python scripts/create_index.py https://<collection-id>.us-east-1.aoss.amazonaws.com
```

---

## Index Field Mapping

The `images` index uses the following schema:

| Field | Type | Notes |
|---|---|---|
| `image_id` | `keyword` | Unique image identifier; used as the OpenSearch document `_id` for idempotent re-indexing |
| `project_id` | `keyword` | Project the image belongs to; used as a filter in search queries |
| `embedding` | `knn_vector` | 1536-dimensional float32 vector from `amazon.titan-embed-image-v1`; engine `faiss`, method `hnsw`, space type `cosine` |
| `tags` | `keyword` | Multi-value list of AI-generated or manual tags (e.g. `["bridge", "concrete crack"]`) |
| `date` | `date` | ISO 8601 date/datetime string (e.g. `"2024-04-15T08:30:00-07:00"`) |
| `location` | `keyword` | Human-readable location string (e.g. `"Pier P-3, East Side"`) |

**Embedding field rationale:**
- `dimension: 1536` — matches the output of `amazon.titan-embed-image-v1` exactly.
- `space_type: cosine` — Titan Multimodal embeddings are not unit-normalised, so cosine similarity (which normalises internally) produces correct rankings. Dot product on non-normalised vectors would not.
- `engine: faiss` — the recommended engine for OpenSearch Serverless; `nmslib` is not supported in AOSS.
- `method: hnsw` — Hierarchical Navigable Small World graph; the standard approximate nearest-neighbour algorithm supported by AOSS.

---

## Handoff: Dev 3 (Bedrock Embeddings)

Dev 3 is responsible for generating embeddings from images using Amazon Bedrock and indexing them into the vector store.

### Function signature

```python
from vector_store import VectorStore

vs = VectorStore()  # reads OPENSEARCH_ENDPOINT from environment

result = vs.index_image(
    image_id: str,
    project_id: str,
    embedding: list[float],
    tags: list[str],
    date: str,
    location: str,
) -> dict
```

### Parameter descriptions

| Parameter | Type | Description |
|---|---|---|
| `image_id` | `str` | Unique identifier for the image (e.g. `"site-photo-01.jpg"`). Used as the document `_id` — re-indexing the same `image_id` overwrites the existing document. |
| `project_id` | `str` | Project identifier (e.g. `"PROJ-001"`). |
| `embedding` | `list[float]` | **Must be exactly 1536 floats.** The raw output of `amazon.titan-embed-image-v1` — do not normalise before passing. |
| `tags` | `list[str]` | Tags describing the image content (e.g. `["bridge", "concrete", "pier"]`). |
| `date` | `str` | ISO 8601 date or datetime string (e.g. `"2024-04-15T08:30:00-07:00"`). |
| `location` | `str` | Human-readable location string (e.g. `"Pier P-3, East Side"`). |

A `ValueError` is raised immediately if `len(embedding) != 1536` — no network call is made.

### Example call

```python
import os
from vector_store import VectorStore

os.environ["OPENSEARCH_ENDPOINT"] = "https://<collection-id>.us-east-1.aoss.amazonaws.com"

vs = VectorStore()

# embedding is the 1536-float list returned by Bedrock Titan Multimodal
response = vs.index_image(
    image_id="site-photo-01.jpg",
    project_id="PROJ-001",
    embedding=[0.012, -0.034, ...],  # 1536 floats from Bedrock
    tags=["bridge", "concrete", "pier"],
    date="2024-04-15T08:30:00-07:00",
    location="Pier P-3, East Side",
)

print(response)
# {'_index': 'images', '_id': 'site-photo-01.jpg', 'result': 'created', ...}
```

---

## Handoff: Dev 5 (Search API)

Dev 5 is responsible for building the search API that accepts a query embedding and returns ranked image results.

### Function signature

```python
from vector_store import VectorStore

vs = VectorStore()  # reads OPENSEARCH_ENDPOINT from environment

results = vs.search_by_embedding(
    embedding_vector: list[float],
    top_k: int = 10,
    filters: dict | None = None,
) -> list[dict]
```

### Parameter descriptions

| Parameter | Type | Default | Description |
|---|---|---|---|
| `embedding_vector` | `list[float]` | — | **Must be exactly 1536 floats.** The query embedding to search against. |
| `top_k` | `int` | `10` | Maximum number of results to return. |
| `filters` | `dict \| None` | `None` | Optional OpenSearch bool filter clause. See filter format below. |

A `ValueError` is raised immediately if `len(embedding_vector) != 1536`.

### Filter parameter format

Filters are standard OpenSearch query clauses passed as a dict. They are embedded inside a `bool.filter` clause in the kNN query, so they narrow results without affecting the similarity score.

**Filter by project:**
```python
filters={"term": {"project_id": "PROJ-001"}}
```

**Filter by date range:**
```python
filters={"range": {"date": {"gte": "2024-01-01", "lte": "2024-12-31"}}}
```

**No filter (return results from all projects):**
```python
filters=None
```

### Result object structure

Each item in the returned list has the following keys:

| Key | Type | Description |
|---|---|---|
| `image_id` | `str` | Unique image identifier |
| `project_id` | `str` | Project the image belongs to |
| `tags` | `list[str]` | Tags associated with the image |
| `date` | `str` | ISO 8601 date string |
| `location` | `str` | Human-readable location string |
| `score` | `float` | Cosine similarity score (higher is more similar) |

Results are returned in descending score order (most similar first).

### Example call

```python
import os
from vector_store import VectorStore

os.environ["OPENSEARCH_ENDPOINT"] = "https://<collection-id>.us-east-1.aoss.amazonaws.com"

vs = VectorStore()

# Search for the top 5 images most similar to a query embedding,
# restricted to project PROJ-001
results = vs.search_by_embedding(
    embedding_vector=[0.021, -0.015, ...],  # 1536 floats from Bedrock
    top_k=5,
    filters={"term": {"project_id": "PROJ-001"}},
)

for r in results:
    print(r["image_id"], r["score"], r["tags"])

# Example output:
# site-photo-03.jpg 0.9821 ['bridge', 'concrete', 'crack']
# site-photo-07.jpg 0.9614 ['pier', 'corrosion']
# site-photo-01.jpg 0.9402 ['bridge', 'concrete', 'pier']
```
