# Implementation Plan: Visual Project Intelligence Search — P2 AWS Rekognition Labelling

## Overview

This task list covers the P2 track (Tagging Handler Lambda) across all three hackathon phases. The Lambda consumes messages from `tagging-queue`, calls Rekognition `DetectLabels`, normalises the returned labels, and forwards enriched messages to `embedding-queue`. Tasks are ordered to deliver a working, tested Lambda by the end of Phase 1, integrate it into the pipeline in Phase 2, and instrument KPIs in Phase 3.

Implementation language: **Python** (boto3 for AWS SDK calls, pytest + Hypothesis for property-based tests).

## Tasks

- [x] 1. Create the Tagging Handler Lambda skeleton and IAM role
  - [x] 1.1 Create the Lambda function file `tagging_handler/handler.py` with an SQS event handler entry point
    - Parse the SQS event records and extract `image_id`, `project_id`, `s3_bucket`, `s3_key` from each message body
    - Add environment variable bindings: `EMBEDDING_QUEUE_URL`, `CLOUDWATCH_NAMESPACE`, `AWS_REGION`
    - Return a batch item failure list so partial batch failures are handled correctly
    - _Requirements: 2.1_
  - [x] 1.2 Define the IAM role and policy for the Tagging Handler
    - Create `tagging_handler/iam_policy.json` granting `rekognition:DetectLabels`, `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on `tagging-queue`, `sqs:SendMessage` on `embedding-queue`, and `cloudwatch:PutMetricData`
    - _Requirements: 2.1, 2.6_
  - [x] 1.3 Wire the Lambda trigger to SQS `tagging-queue`
    - Add the SQS event source mapping configuration (batch size 10, bisect-on-error enabled) to `tagging_handler/template.yaml` or equivalent IaC file
    - _Requirements: 2.1_

- [x] 2. Implement Rekognition label detection
  - [x] 2.1 Implement the `detect_labels` function in `tagging_handler/rekognition.py`
    - Call `rekognition:DetectLabels` with `S3Object` input (`Bucket`, `Name`) and `MinConfidence: 70`
    - Return the raw label list from the Rekognition response
    - _Requirements: 2.1, 2.2_
  - [ ]* 2.2 Write property test for confidence threshold filtering (Property 2)
    - **Property 2: Confidence threshold filtering retains exactly the right labels**
    - Generate lists of labels with random confidence values 0–100 using Hypothesis `@given(st.lists(st.fixed_dictionaries({'Name': st.text(), 'Confidence': st.floats(min_value=0, max_value=100)})))`
    - Assert that only labels with `Confidence >= 70` appear in the filtered output and all others are absent
    - **Validates: Requirements 2.2**
  - [x] 2.3 Implement retry logic for Rekognition API failures
    - Wrap the `detect_labels` call with 3× exponential backoff: delays of 100 ms, 200 ms, 400 ms on `ClientError` / transient exceptions
    - After 3 failed attempts, raise the exception to trigger SQS dead-lettering to `tagging-dlq`
    - _Requirements: 2.6_

- [x] 3. Implement tag normalisation
  - [x] 3.1 Implement the `normalise_tags` function in `tagging_handler/normaliser.py`
    - Step 1: `label.lower()` for all labels
    - Step 2: Remove duplicates using a case-insensitive set (preserve insertion order)
    - Step 3: Strip non-alphanumeric characters except hyphens and spaces using `re.sub(r'[^a-z0-9\- ]', '', label)`
    - Step 4: `label.strip()` to remove leading/trailing whitespace
    - Return the resulting list of normalised tag strings
    - _Requirements: 2.3, 2.7_
  - [ ]* 3.2 Write property test for tag normalisation idempotency (Property 1)
    - **Property 1: Tag normalisation is idempotent and produces canonical output**
    - Generate arbitrary lists of strings using Hypothesis `@given(st.lists(st.text()))`
    - Assert that `normalise_tags(normalise_tags(labels)) == normalise_tags(labels)` (idempotent)
    - Assert that every string in the output is entirely lowercase
    - Assert that the output contains no duplicate values
    - **Validates: Requirements 2.3, 2.7**
  - [ ]* 3.3 Write unit tests for tag normalisation edge cases
    - Test: mixed-case input → all lowercase output
    - Test: duplicate labels (exact and case-variant) → deduplicated output
    - Test: labels with special characters (e.g. `"Steel Beam!"`) → stripped to `"steel beam"`
    - Test: empty input list → empty output list
    - Test: labels with only non-alphanumeric characters → empty strings filtered out
    - _Requirements: 2.3, 2.7_

- [~] 4. Checkpoint — Phase 1 unit tests passing
  - Ensure all unit tests and property tests for `detect_labels`, `normalise_tags`, and the handler entry point pass locally. Ask the user if questions arise.

- [ ] 5. Handle zero-labels case and forward to embedding-queue
  - [~] 5.1 Implement zero-labels handling in the handler
    - After normalisation, if the tag list is empty, emit a `TaggingZeroLabels` CloudWatch metric with namespace `VisualProjectIntelligenceSearch` and dimension `project_id`
    - Log a structured CloudWatch log entry: `{"event": "TaggingZeroLabels", "image_id": ..., "project_id": ...}`
    - Continue processing (do not dead-letter) — forward the message to `embedding-queue` with an empty `tags` list
    - _Requirements: 2.5_
  - [~] 5.2 Implement the `forward_to_embedding_queue` function in `tagging_handler/queue.py`
    - Construct the output message: `{ "image_id", "project_id", "s3_bucket", "s3_key", "tags": [...], "date": "<ISO8601 from metadata or empty string>", "location": "<from metadata or empty string>" }`
    - Send the message to `EMBEDDING_QUEUE_URL` via `sqs:SendMessage`
    - _Requirements: 2.4_
  - [ ]* 5.3 Write unit tests for the queue forwarding function
    - Test: valid tags list → message body matches expected schema
    - Test: empty tags list → message body contains `"tags": []`
    - Test: SQS send failure raises exception (to trigger retry/DLQ)
    - _Requirements: 2.4, 2.5_

- [ ] 6. Checkpoint — Phase 2 integration test
  - [~] 6.1 Write integration test: consume a real SQS message from `tagging-queue` and verify output on `embedding-queue`
    - Send a test message to `tagging-queue` with a known `image_id`, `project_id`, `s3_bucket`, `s3_key` pointing to a real test image in S3
    - Invoke the Lambda handler directly (or via `aws lambda invoke`) and poll `embedding-queue` for the output message
    - Assert the output message contains `tags` (non-empty array), `image_id`, `project_id`, `s3_bucket`, `s3_key`
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - Ensure all unit and property tests still pass. Ask the user if questions arise.

- [ ] 7. KPI instrumentation — Phase 3
  - [~] 7.1 Emit `TaggingSuccess` CloudWatch metric on successful tag extraction
    - After a successful `forward_to_embedding_queue` call, emit a `TaggingSuccess` metric to namespace `VisualProjectIntelligenceSearch` with dimension `project_id` and unit `Count`
    - _Requirements: 10.1, 10.4_
  - [ ]* 7.2 Write unit tests for CloudWatch metric emission
    - Test: successful tagging path → `TaggingSuccess` metric emitted with correct namespace and `project_id` dimension
    - Test: zero-labels path → `TaggingZeroLabels` metric emitted with correct namespace and `project_id` dimension
    - Test: neither metric is emitted when the handler raises before reaching the emit call
    - _Requirements: 10.1, 10.4_
  - [ ]* 7.3 Write property test for CloudWatch namespace correctness (Property 17)
    - **Property 17: CloudWatch metrics use the correct namespace and include project_id dimension**
    - Generate arbitrary `project_id` strings using Hypothesis `@given(st.text(min_size=1))`
    - Mock the Rekognition and SQS calls; invoke the handler with a synthetic event
    - Assert every `put_metric_data` call uses namespace `VisualProjectIntelligenceSearch` and includes a `project_id` dimension
    - **Validates: Requirements 10.1, 10.4**

- [ ] 8. Smoke test verification — Phase 3
  - [~] 8.1 Verify tags appear correctly on ingested images during smoke test
    - After uploading 10 real project images through the full pipeline, query the `embedding-queue` output messages and assert each contains a non-empty `tags` array
    - Confirm at least one tag per image is a recognisable construction-domain label (e.g. "building", "concrete", "crane")
    - _Requirements: 11.1_
  - [~] 8.2 Confirm tag data flows through to OpenSearch Index_Records
    - Query the OpenSearch `image-embeddings` index for each ingested `image_id` and assert the `tags` field is present and matches the normalised tags forwarded by the Tagging Handler
    - _Requirements: 2.4, 11.1_

- [~] 9. Final checkpoint — all P2 tests passing
  - Ensure all unit tests, property tests, and integration tests for the P2 track pass. Confirm `TaggingSuccess` and `TaggingZeroLabels` metrics appear in CloudWatch under the correct namespace. Ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- The Tagging Handler never blocks the pipeline on zero labels — it always forwards to `embedding-queue`
- Dead-lettering to `tagging-dlq` only occurs after 3 failed Rekognition retries; the SQS event source mapping handles this automatically when the handler raises
- Property tests use Hypothesis; install with `pip install hypothesis pytest boto3 moto`
- The `date` and `location` fields in the `embedding-queue` message are sourced from DynamoDB Image_Record metadata (P1 output); if unavailable, forward empty strings rather than omitting the fields

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1", "3.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.2", "3.3"] },
    { "id": 3, "tasks": ["5.1", "5.2"] },
    { "id": 4, "tasks": ["5.3", "6.1"] },
    { "id": 5, "tasks": ["7.1"] },
    { "id": 6, "tasks": ["7.2", "7.3"] },
    { "id": 7, "tasks": ["8.1"] },
    { "id": 8, "tasks": ["8.2"] }
  ]
}
```
