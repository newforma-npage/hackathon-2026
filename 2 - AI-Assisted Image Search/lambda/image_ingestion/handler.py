"""
Lambda handler: S3 ObjectCreated → extract metadata → write to DynamoDB.

Expected S3 key structure:  {project_id}/{filename}
  e.g.  PROJ-001/site-photo-01.jpg

DynamoDB record written:
  project_id  (PK)  – e.g. "PROJ-001"
  image_path  (SK)  – full S3 key, e.g. "PROJ-001/site-photo-01.jpg"
  bucket_name       – source S3 bucket
  filename          – bare filename, e.g. "site-photo-01.jpg"
  timestamp         – ISO-8601 UTC timestamp of the S3 event
  ai_indexed        – False (will be set True after Rekognition/Bedrock step)
"""

import json
import logging
import os
from datetime import datetime, timezone
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

PHOTO_TABLE_NAME = os.environ["PHOTO_TABLE_NAME"]

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(PHOTO_TABLE_NAME)


def _parse_project_id(s3_key: str) -> str:
    """
    Extract project_id from the first path segment of the S3 key.

    e.g. "PROJ-001/site-photo-01.jpg"  →  "PROJ-001"

    Raises ValueError if the key has no path separator (flat key with no
    project prefix), so the caller can decide how to handle it.
    """
    parts = s3_key.split("/", 1)
    if len(parts) < 2 or not parts[0]:
        raise ValueError(
            f"S3 key '{s3_key}' does not follow the expected "
            "'{{project_id}}/{{filename}}' structure."
        )
    return parts[0]


def _build_record(bucket: str, key: str, event_time: str) -> dict:
    """Build the DynamoDB item from S3 event fields."""
    import uuid as _uuid
    project_id = _parse_project_id(key)
    filename = key.rsplit("/", 1)[-1]

    # Generate a deterministic photo_id from the filename so the FastAPI
    # enrichment pipeline (which uses uuid5(NAMESPACE_URL, filename)) can
    # look up the same record without a separate key-translation step.
    photo_id = str(_uuid.uuid5(_uuid.NAMESPACE_URL, filename))

    return {
        "project_id": project_id,
        "image_path": key,          # sort key — unique per image
        "photo_id": photo_id,       # matches the vector store key used by main.py
        "bucket_name": bucket,
        "filename": filename,
        "timestamp": event_time,    # ISO-8601 string from S3 event
        "ai_indexed": False,        # will be set True by the AI enrichment step
    }


def lambda_handler(event: dict, context) -> dict:
    """
    Entry point.  Processes all S3 records in the event batch.

    Returns a summary dict with counts of successes and failures.
    Partial failures are logged but do not raise — this prevents SQS/S3
    from retrying the entire batch when only one record fails.
    """
    records = event.get("Records", [])
    logger.info("Received %d S3 record(s)", len(records))

    successes = 0
    failures = 0

    for record in records:
        bucket = record["s3"]["bucket"]["name"]
        # S3 URL-encodes the key; decode it back to a normal path string
        key = unquote_plus(record["s3"]["object"]["key"])
        event_time = record.get("eventTime", datetime.now(timezone.utc).isoformat())

        logger.info("Processing s3://%s/%s", bucket, key)

        try:
            item = _build_record(bucket, key, event_time)

            # Upsert — safe to call multiple times for the same image
            table.put_item(Item=item)

            logger.info(
                "Stored metadata: project_id=%s image_path=%s",
                item["project_id"],
                item["image_path"],
            )
            successes += 1

        except ValueError as exc:
            # Key doesn't match expected structure — log and skip
            logger.warning("Skipping record: %s", exc)
            failures += 1

        except ClientError as exc:
            logger.error(
                "DynamoDB error for s3://%s/%s: %s",
                bucket,
                key,
                exc.response["Error"]["Message"],
            )
            failures += 1

    result = {"processed": successes, "skipped_or_failed": failures}
    logger.info("Done: %s", result)
    return result
