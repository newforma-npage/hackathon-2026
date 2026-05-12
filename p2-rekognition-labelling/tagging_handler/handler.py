"""
Tagging Handler Lambda — P2 AWS Rekognition Labelling

Triggered by SQS tagging-queue. For each message, calls Rekognition DetectLabels,
normalises the returned labels, and forwards an enriched message to embedding-queue.

Requirements: 2.1, 2.6
"""

import json
import logging
import os
from typing import Any

from tagging_handler.rekognition import detect_labels_with_retry

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Environment variable bindings
# ---------------------------------------------------------------------------

EMBEDDING_QUEUE_URL: str = os.environ.get("EMBEDDING_QUEUE_URL", "")
CLOUDWATCH_NAMESPACE: str = os.environ.get(
    "CLOUDWATCH_NAMESPACE", "VisualProjectIntelligenceSearch"
)
AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")


# ---------------------------------------------------------------------------
# Stub — will be replaced by the real implementation in task 2.x / 3.x
# ---------------------------------------------------------------------------

def process_record(
    image_id: str,
    project_id: str,
    s3_bucket: str,
    s3_key: str,
) -> None:
    """
    Process a single tagging-queue record.

    Calls Rekognition DetectLabels (with retry logic) on the S3 image.
    Full tag normalisation and forwarding to embedding-queue will be added
    in subsequent tasks (3.1, 5.1, 5.2).

    Args:
        image_id:   Unique identifier for the image.
        project_id: NPC project identifier.
        s3_bucket:  S3 bucket containing the image.
        s3_key:     S3 object key for the image.

    Raises:
        Exception: Any unhandled error causes the record to be added to the
                   batch item failure list so SQS can retry it individually.
    """
    logger.info(
        "Processing record",
        extra={
            "image_id": image_id,
            "project_id": project_id,
            "s3_bucket": s3_bucket,
            "s3_key": s3_key,
        },
    )
    # Call Rekognition with retry/backoff (task 2.3); raises on exhausted retries
    raw_labels = detect_labels_with_retry(s3_bucket, s3_key)
    # TODO (task 3.1): call normalise_tags(raw_labels)
    # TODO (task 5.1): handle zero-labels case (emit CloudWatch metric)
    # TODO (task 5.2): forward TagsReady message to EMBEDDING_QUEUE_URL


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, list[dict]]:
    """
    SQS event handler entry point.

    Iterates over all SQS records in the batch, parses each message body,
    and calls process_record(). Any record that raises an exception is
    collected into the batchItemFailures list so SQS can retry it
    individually without reprocessing successful records.

    Args:
        event:   Standard AWS Lambda SQS event dict containing a 'Records'
                 list.  Each record has a 'messageId' and a 'body' field
                 (JSON-encoded string).
        context: Lambda context object (unused but required by the runtime).

    Returns:
        A dict with a single key ``batchItemFailures`` whose value is a list
        of ``{"itemIdentifier": <messageId>}`` dicts for every record that
        failed processing.  An empty list means the entire batch succeeded.
    """
    batch_item_failures: list[dict[str, str]] = []

    records = event.get("Records", [])
    logger.info("Received SQS batch", extra={"record_count": len(records)})

    for record in records:
        message_id: str = record.get("messageId", "")
        try:
            body: dict = json.loads(record["body"])

            image_id: str = body["image_id"]
            project_id: str = body["project_id"]
            s3_bucket: str = body["s3_bucket"]
            s3_key: str = body["s3_key"]

            process_record(
                image_id=image_id,
                project_id=project_id,
                s3_bucket=s3_bucket,
                s3_key=s3_key,
            )

        except (KeyError, json.JSONDecodeError) as exc:
            logger.error(
                "Malformed message body — adding to batch item failures",
                extra={"message_id": message_id, "error": str(exc)},
            )
            batch_item_failures.append({"itemIdentifier": message_id})

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "Unexpected error processing record — adding to batch item failures",
                extra={"message_id": message_id, "error": str(exc)},
            )
            batch_item_failures.append({"itemIdentifier": message_id})

    logger.info(
        "Batch processing complete",
        extra={
            "total": len(records),
            "failures": len(batch_item_failures),
        },
    )

    return {"batchItemFailures": batch_item_failures}
