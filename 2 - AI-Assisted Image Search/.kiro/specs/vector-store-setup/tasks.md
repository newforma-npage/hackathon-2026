# Tasks: Vector Store + Schema Setup

## Task List

- [x] 1. CDK Stack — Provision OpenSearch Serverless Collection
- [x] 2. Index Creation Script — Create `images` Index with Field Mapping
- [x] 3. VectorStore Client Module — Python Helper with SigV4 Auth
- [x] 4. README — Setup Guide and Handoff Notes
- [x] 5. Unit Tests — Example-Based Tests for Mapping, Config, and Delete
- [x] 6. Property-Based Tests — Hypothesis Tests for VectorStore Properties
- [x] 7. CDK Snapshot Tests — Assert Collection Type, Policies, and Output

---

## Task 1: CDK Stack — Provision OpenSearch Serverless Collection

**Description:** Create the AWS CDK (Python) stack that provisions the OpenSearch Serverless collection with all required security policies and outputs the collection endpoint.

**Files to create:**
- `cdk/image_search_stack.py`
- `cdk/app.py`
- `cdk/requirements.txt`

**Dependencies:** None

**Acceptance criteria references:** Requirements 1.1–1.6

### Sub-tasks

- [x] 1.1 Create `cdk/requirements.txt` with pinned `aws-cdk-lib>=2.0.0,<3.0.0` and `constructs>=10.0.0,<11.0.0` dependencies
- [x] 1.2 Create `cdk/image_search_stack.py` with `ImageSearchStack(Stack)` class
  - [x] 1.2.1 Define `CfnCollection` resource named `image-search` with `type="VECTORSEARCH"` in `us-east-1`
  - [x] 1.2.2 Define `CfnSecurityPolicy` for encryption using AWS-owned KMS keys (`type="encryption"`)
  - [x] 1.2.3 Define `CfnSecurityPolicy` for network access allowing public access for both OpenSearch API and Dashboards endpoints (`type="network"`)
  - [x] 1.2.4 Define `CfnAccessPolicy` for data access granting `aoss:*` on all indexes to the deploying IAM principal and any specified application role ARN (`type="data"`)
  - [x] 1.2.5 Add `CfnOutput` named `CollectionEndpoint` that outputs the collection's HTTPS endpoint URL
- [x] 1.3 Create `cdk/app.py` as the CDK entry point that instantiates `ImageSearchStack` and calls `app.synth()`

---

## Task 2: Index Creation Script — Create `images` Index with Field Mapping

**Description:** Create a standalone Python script that connects to the OpenSearch Serverless collection and creates the `images` index with the exact field mapping required by the system.

**Files to create:**
- `scripts/create_index.py`

**Dependencies:** Task 1 (collection endpoint must exist)

**Acceptance criteria references:** Requirements 2.1–2.10, 4.1–4.2

### Sub-tasks

- [x] 2.1 Implement `build_index_mapping() -> dict` function that returns the full index settings and mappings dict:
  - `settings`: `{"index.knn": true}`
  - `image_id`: `keyword`
  - `project_id`: `keyword`
  - `embedding`: `knn_vector`, dimension `1536`, engine `faiss`, space_type `cosine`, method `hnsw`
  - `tags`: `keyword`
  - `date`: `date`
  - `location`: `keyword`
- [x] 2.2 Implement SigV4 authentication using `boto3.Session` and `opensearchpy.AWSV4SignerAuth`
- [x] 2.3 Read the collection endpoint from the `OPENSEARCH_ENDPOINT` environment variable (with optional CLI argument override)
- [x] 2.4 Call `client.indices.create()` with the mapping from `build_index_mapping()`
- [x] 2.5 Handle the case where the index already exists: catch `RequestError` with status 400, log an `INFO` message (`"Index already exists, skipping"`), and continue without raising

---

## Task 3: VectorStore Client Module — Python Helper with SigV4 Auth

**Description:** Create the `vector_store.py` module that wraps the OpenSearch Serverless client and exposes `index_image`, `search_by_embedding`, and `delete_image` with SigV4 authentication, full docstrings, and error handling.

**Files to create:**
- `vector_store.py`

**Dependencies:** Task 2 (index must exist before operations are meaningful)

**Acceptance criteria references:** Requirements 3.1–3.9, 5.1–5.5

### Sub-tasks

- [x] 3.1 Implement `VectorStore.__init__(self, endpoint: str | None = None)`:
  - Accept endpoint as constructor parameter; fall back to `OPENSEARCH_ENDPOINT` env var
  - Raise `ValueError` with a clear message if neither is provided
  - Initialise the `opensearchpy.OpenSearch` client with `AWSV4SignerAuth` using `boto3` credentials for the `aoss` service
  - Include docstring per design spec
- [x] 3.2 Implement `VectorStore.index_image(image_id, project_id, embedding, tags, date, location) -> dict`:
  - Validate `len(embedding) == 1536`; raise `ValueError` with descriptive message if not
  - Use `image_id` as the document `_id` for idempotent re-indexing
  - Call `client.index(index="images", id=image_id, body={...})`
  - Wrap in try/except: catch `OpenSearchException`, log `ERROR` with operation name and exception detail, re-raise
  - Include docstring per design spec
- [x] 3.3 Implement `VectorStore.search_by_embedding(embedding_vector, top_k=10, filters=None) -> list[dict]`:
  - Validate `len(embedding_vector) == 1536`; raise `ValueError` if not
  - Build the kNN query body with `size=top_k` and the `knn.embedding` clause
  - When `filters` is provided, embed it as a `bool.filter` clause inside the kNN query
  - Map each OpenSearch hit to a result dict with keys: `image_id`, `project_id`, `tags`, `date`, `location`, `score`
  - Wrap in try/except: catch `OpenSearchException`, log `ERROR`, re-raise
  - Include docstring per design spec
- [x] 3.4 Implement `VectorStore.delete_image(image_id: str) -> dict`:
  - Call `client.delete(index="images", id=image_id)`
  - Catch `NotFoundError` (404) and return an empty dict without re-raising
  - Catch all other `OpenSearchException`, log `ERROR`, re-raise
  - Include docstring per design spec

---

## Task 4: README — Setup Guide and Handoff Notes

**Description:** Create a `README.md` that documents the setup steps, the `CollectionEndpoint` output, the index schema, and handoff notes for Dev 3 (Bedrock embeddings) and Dev 5 (Search API).

**Files to create:**
- `README.md`

**Dependencies:** Tasks 1, 2, 3

**Acceptance criteria references:** Requirements 4.3–4.5

### Sub-tasks

- [x] 4.1 Write prerequisites section (Python 3.11+, AWS CDK v2, boto3, opensearch-py, AWS credentials with AOSS permissions)
- [x] 4.2 Write CDK deployment steps (`cdk bootstrap`, `cdk deploy`) and document the `CollectionEndpoint` CloudFormation output
- [x] 4.3 Write index creation steps (set `OPENSEARCH_ENDPOINT`, run `python scripts/create_index.py`)
- [x] 4.4 Document the full index field mapping table (field name, type, notes)
- [x] 4.5 Write **Handoff: Dev 3 (Bedrock Embeddings)** section:
  - Expected embedding format: 1536-dim `list[float]` from `amazon.titan-embed-image-v1`
  - `index_image` function signature and parameter descriptions
  - Example call
- [x] 4.6 Write **Handoff: Dev 5 (Search API)** section:
  - `search_by_embedding` function signature and parameter descriptions
  - Filter parameter format with examples (`term`, `range`)
  - Structure of returned result objects
  - Example call

---

## Task 5: Unit Tests — Example-Based Tests

**Description:** Create example-based unit tests that verify mapping correctness, endpoint configuration behaviour, and graceful handling of delete on a non-existent document.

**Files to create:**
- `tests/test_vector_store.py`

**Dependencies:** Tasks 2, 3

**Acceptance criteria references:** Requirements 2.1–2.8, 3.7, 5.4

### Sub-tasks

- [x] 5.1 Test `build_index_mapping()` returns the exact mapping structure:
  - `settings["index.knn"]` is `True`
  - `image_id`, `project_id`, `tags`, `location` are `keyword`
  - `date` is `date`
  - `embedding` is `knn_vector` with `dimension=1536`, `engine="faiss"`, `space_type="cosine"`, `method.name="hnsw"`
- [x] 5.2 Test `VectorStore.__init__` raises `ValueError` when neither constructor arg nor `OPENSEARCH_ENDPOINT` env var is set
- [x] 5.3 Test `VectorStore.__init__` uses the constructor argument endpoint when provided (mock the OpenSearch client)
- [x] 5.4 Test `VectorStore.__init__` falls back to `OPENSEARCH_ENDPOINT` env var when no constructor arg is given (mock the OpenSearch client)
- [x] 5.5 Test `VectorStore.delete_image` returns an empty dict and does not raise when the mock client raises `NotFoundError` (404)

---

## Task 6: Property-Based Tests — Hypothesis Tests

**Description:** Create property-based tests using Hypothesis that verify the 7 correctness properties defined in the design document. The OpenSearch client is mocked so tests run in-memory.

**Files to create:**
- `tests/test_vector_store_pbt.py`

**Dependencies:** Task 3

**Acceptance criteria references:** Requirements 3.1–3.9, 5.1–5.5 (via Properties 1–7)

**PBT framework:** Hypothesis with `@settings(max_examples=100)`

### Sub-tasks

- [x] 6.1 **Property 1 — Index round-trip preserves document data**
  - Strategy: `st.text()` for string fields, `st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=1536, max_size=1536)` for embedding, `st.lists(st.text())` for tags
  - Mock client `index()` stores the body; mock `get()` returns it
  - Assert `_source` fields equal the indexed values
  - Annotate: `# Feature: vector-store-setup, Property 1: Index round-trip preserves document data`
  - **Validates: Requirements 3.1, 3.2, 5.2**
- [x] 6.2 **Property 2 — Re-indexing the same image_id is idempotent**
  - Strategy: generate two document payloads sharing one `image_id`
  - Mock client tracks the last indexed body per `_id`
  - Assert only one document exists and its `_source` matches `doc_b`
  - Annotate: `# Feature: vector-store-setup, Property 2: Re-indexing the same image_id is idempotent`
  - **Validates: Requirements 5.1**
- [x] 6.3 **Property 3 — Search results satisfy top_k bound and contain required fields**
  - Strategy: `st.integers(min_value=1, max_value=100)` for `top_k`; mock client returns exactly `top_k` hits
  - Assert `len(results) <= top_k` and each result contains `image_id`, `project_id`, `tags`, `date`, `location`, `score`
  - Annotate: `# Feature: vector-store-setup, Property 3: Search results satisfy top_k bound and contain required fields`
  - **Validates: Requirements 3.3, 5.2, 5.3**
- [x] 6.4 **Property 4 — Filter clause is correctly embedded in the kNN query**
  - Strategy: `st.dictionaries(st.text(min_size=1), st.text(min_size=1))` for filter dict
  - Capture the query body passed to the mock client's `search()` call
  - Assert the `knn` clause is present and the `bool.filter` clause matches the provided filter
  - Annotate: `# Feature: vector-store-setup, Property 4: Filter clause is correctly embedded in the kNN query`
  - **Validates: Requirements 3.4**
- [x] 6.5 **Property 5 — Delete round-trip removes the document; deleting non-existent image is safe**
  - Strategy: `st.text(min_size=1)` for `image_id`
  - Mock client tracks indexed docs; after `index_image` + `delete_image`, mock `get()` returns not-found
  - Assert calling `delete_image` on a never-indexed `image_id` does not raise
  - Annotate: `# Feature: vector-store-setup, Property 5: Delete round-trip removes the document; deleting non-existent image is safe`
  - **Validates: Requirements 3.5, 5.4**
- [x] 6.6 **Property 6 — Embedding dimension validation rejects non-1536-length inputs**
  - Strategy: `st.lists(st.floats()).filter(lambda x: len(x) != 1536)` for invalid embeddings
  - Assert both `index_image` and `search_by_embedding` raise `ValueError` before any mock client call is made
  - Annotate: `# Feature: vector-store-setup, Property 6: Embedding dimension validation rejects non-1536-length inputs`
  - **Validates: Requirements 5.5**
- [x] 6.7 **Property 7 — All VectorStore operations log and re-raise OpenSearch exceptions**
  - Strategy: `st.sampled_from(["index_image", "search_by_embedding", "delete_image"])` for operation; mock client raises `OpenSearchException`
  - Assert the exception is re-raised and an `ERROR` log entry containing the operation name and exception detail was emitted
  - Annotate: `# Feature: vector-store-setup, Property 7: All VectorStore operations log and re-raise OpenSearch exceptions`
  - **Validates: Requirements 3.8**

---

## Task 7: CDK Snapshot Tests — Assert Collection Type, Policies, and Output

**Description:** Create CDK snapshot/assertion tests using `aws_cdk.assertions.Template` that verify the synthesised CloudFormation template contains the correct resources and outputs.

**Files to create:**
- `tests/test_cdk_stack.py`

**Dependencies:** Task 1

**Acceptance criteria references:** Requirements 1.1–1.5

### Sub-tasks

- [x] 7.1 Synthesise the `ImageSearchStack` in the test and obtain a `Template` object via `Template.from_stack()`
- [x] 7.2 Assert the template contains exactly one `AWS::OpenSearchServerless::Collection` resource with `Type: VECTORSEARCH`
- [x] 7.3 Assert the template contains a `AWS::OpenSearchServerless::SecurityPolicy` resource with `Type: encryption`
- [x] 7.4 Assert the template contains a `AWS::OpenSearchServerless::SecurityPolicy` resource with `Type: network`
- [x] 7.5 Assert the template contains a `AWS::OpenSearchServerless::AccessPolicy` resource with `Type: data`
- [x] 7.6 Assert the template has a CloudFormation output named `CollectionEndpoint`
