# Implementation Plan: P3 — Natural-Language Query → Vector Search

## Overview

Implement the natural-language search path in the Search Handler Lambda: accept `POST /search`, embed the query text via Bedrock Titan Multimodal (text mode), execute an ANN kNN query against the `image-embeddings` OpenSearch Serverless index with pre-filter support, and return top-K ranked results. Includes JWT auth validation, structured error handling, unit tests with mocked AWS clients, and an integration test against the live index.

**Prerequisites**: t3 (Bedrock embeddings setup) and t5 (Search API skeleton) must be complete before starting.

**Language**: Python (boto3, opensearch-py)

---

## Tasks

- [x] 1. Implement query text embedding via Bedrock
  - [x] 1.1 Add `embed_query_text` function to the Search Handler Lambda
    - In `lambda/search_handler/handler.py` (or equivalent), import `boto3` and create a Bedrock Runtime client
    - Call `bedrock_runtime.invoke_model` with model ID `amazon.titan-embed-image-v1` and body `{"inputText": "<query string>"}`
    - Parse the response JSON and extract the `embedding` field (1024-dim float list)
    - Raise a typed `BedrockUnavailableError` on `ClientError` / timeout so the caller can map it to HTTP 503
    - _Requirements: 3.2, 5.1_

  - [ ]* 1.2 Write unit test for `embed_query_text`
    - Mock `boto3` Bedrock Runtime client with `unittest.mock.patch`
    - Assert: valid input returns a list of 1024 floats
    - Assert: `ClientError` from Bedrock raises `BedrockUnavailableError`
    - _Requirements: 3.2, 3.5_

- [x] 2. Build the OpenSearch ANN query with pre-filters
  - [x] 2.1 Implement `build_knn_query` function
    - Accept `query_vector` (list[float]), `k` (int), and `filters` dict (`project_id`, `date_from`, `date_to`, `location`, `tags`)
    - Construct an OpenSearch `bool` query: `filter` clause for each active filter dimension (project_id exact match, date range, location term, tags terms), `must` clause containing the `knn` vector search on the `embedding` field of the `image-embeddings` index
    - Apply all filter dimensions as logical AND (each active filter adds one entry to `bool.filter`)
    - Default `k` to 20; cap at 100
    - _Requirements: 4.3, 4.4, 5.1, 7.1, 7.2, 7.3_

  - [ ]* 2.2 Write unit tests for `build_knn_query`
    - Assert: no filters → query has empty `bool.filter` list and `knn` in `bool.must`
    - Assert: `project_id` filter → `term` entry appears in `bool.filter`
    - Assert: date range filter → `range` entry appears in `bool.filter`
    - Assert: multiple filters → all appear in `bool.filter` (logical AND)
    - Assert: `k` > 100 is clamped to 100
    - _Requirements: 4.3, 4.4, 7.3_

- [x] 3. Execute ANN search and parse results
  - [x] 3.1 Implement `run_ann_search` function
    - Accept the built kNN query dict and an OpenSearch client (opensearch-py `OpenSearch`)
    - Call `client.search(index="image-embeddings", body=query)`
    - Parse `hits.hits` and map each hit to the result schema: `image_id`, `project_id`, `s3_url`, `tags`, `date`, `location`, `relevance_score` (cosine similarity from `_score`, normalised to 0.0–1.0)
    - Return a list of result dicts; return empty list when `hits.total.value == 0`
    - Raise `OpenSearchUnavailableError` on connection errors
    - _Requirements: 5.2, 5.3, 5.6_

  - [ ]* 3.2 Write unit tests for `run_ann_search`
    - Mock the OpenSearch client's `search` method
    - Assert: well-formed hits → result list with correct field mapping
    - Assert: zero hits → empty list returned (not an error)
    - Assert: connection error → `OpenSearchUnavailableError` raised
    - Assert: `relevance_score` is in range [0.0, 1.0] for all results
    - _Requirements: 5.2, 5.3, 5.6_

- [x] 4. Implement the `POST /search` Lambda handler
  - [x] 4.1 Wire the handler entry point
    - In the Lambda `handler(event, context)` function, parse the API Gateway proxy event body as JSON
    - Extract `query` (str), `k` (int, default 20), and `filters` (dict, default `{}`)
    - Validate: return HTTP 400 with `{"error": "query is required"}` if `query` is absent or empty string
    - Call `embed_query_text(query)` → `build_knn_query(vector, k, filters)` → `run_ann_search(query_obj, os_client)`
    - Return HTTP 200 with `{"results": [...], "count": N}` on success
    - Catch `BedrockUnavailableError` or `OpenSearchUnavailableError` → return HTTP 503 with `{"error": "Search service temporarily unavailable"}`
    - Log search latency in milliseconds to CloudWatch namespace `VisualProjectIntelligenceSearch` (metric: `SearchLatencyMs`)
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 10.1, 10.4_

- [x] 5. Validate JWT auth via Cognito Authorizer
  - [x] 5.1 Confirm Cognito Authorizer is enforced on `POST /search`
    - Verify the API Gateway resource for `POST /search` has the Cognito Authorizer attached (from the Phase 1 skeleton — no new Lambda code required)
    - Add a guard in the handler: if `event["requestContext"]["authorizer"]` is absent or `claims` is missing, return HTTP 401 with `{"error": "Unauthorized"}`
    - This covers the case where the authorizer is bypassed in local/test invocations
    - _Requirements: 5.7_

  - [ ]* 5.2 Write unit test for auth guard
    - Assert: event without `authorizer` context → HTTP 401 response
    - Assert: event with valid `authorizer.claims` → handler proceeds to embedding step
    - _Requirements: 5.7_

- [x] 6. Checkpoint — Ensure all unit tests pass
  - Run `pytest lambda/search_handler/tests/` (or equivalent test path) and confirm all unit tests pass
  - Ensure all mocked AWS calls are correctly patched and no real AWS calls are made during unit tests
  - Ask the user if any questions arise before proceeding to the integration test

- [ ] 7. Write integration test against the live OpenSearch index
  - [~] 7.1 Implement `test_live_text_search` integration test
    - In `lambda/search_handler/tests/test_integration.py`, submit a real `POST /search` request (or invoke the handler directly with a real event) against the live `image-embeddings` index populated by P1/P2
    - Use a representative query string (e.g., `"foundation cracks"` or `"steel beam"`)
    - Assert: HTTP 200 response
    - Assert: `results` array contains at least 1 item
    - Assert: each result contains `image_id`, `project_id`, `s3_url`, `tags`, `date`, `location`, `relevance_score`
    - Assert: `relevance_score` is a float in [0.0, 1.0]
    - Mark the test with `@pytest.mark.integration` so it is excluded from the default unit test run
    - _Requirements: 5.1, 5.2, 5.3, 11.2_

- [~] 8. Final checkpoint — Ensure all tests pass
  - Run unit tests: `pytest lambda/search_handler/tests/ -m "not integration"`
  - Confirm integration test can be run manually: `pytest lambda/search_handler/tests/ -m integration`
  - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- The Cognito Authorizer (task 5) relies on the API Gateway configuration from the Phase 1 skeleton — no new infrastructure changes are needed
- The integration test (task 7.1) requires the live OpenSearch index to be populated by P1/P2 before it can pass
- Bedrock model ID for text-mode embedding: `amazon.titan-embed-image-v1` with body `{"inputText": "..."}`
- OpenSearch index name: `image-embeddings`; result schema field: `embedding` (1024-dim vector)
- CloudWatch namespace: `VisualProjectIntelligenceSearch`; include `project_id` dimension where applicable
- K default: 20, max: 100; enforce the cap in `build_knn_query`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "2.1"] },
    { "id": 1, "tasks": ["1.2", "2.2", "3.1"] },
    { "id": 2, "tasks": ["3.2", "4.1"] },
    { "id": 3, "tasks": ["5.1"] },
    { "id": 4, "tasks": ["5.2"] },
    { "id": 5, "tasks": ["7.1"] }
  ]
}
```
