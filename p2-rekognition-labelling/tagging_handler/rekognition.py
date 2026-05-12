"""
Rekognition integration for the P2 Tagging Handler.

Provides a thin wrapper around the AWS Rekognition DetectLabels API,
including retry logic with exponential backoff for transient failures.

Requirements: 2.1, 2.2, 2.6
"""

import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment variable bindings
# ---------------------------------------------------------------------------

AWS_REGION: str = os.environ.get("AWS_REGION", "us-east-1")

# ---------------------------------------------------------------------------
# Transient error codes that warrant a retry.
# Permanent errors (e.g. invalid image, missing S3 object) are NOT retried.
# ---------------------------------------------------------------------------

_TRANSIENT_ERROR_CODES: frozenset[str] = frozenset(
    {
        "ThrottlingException",
        "ProvisionedThroughputExceededException",
        "LimitExceededException",
        "RequestThrottled",
        "ServiceUnavailableException",
        "InternalServerError",
        "InternalFailure",
        "ServiceFailure",
    }
)

# Exponential backoff delays in seconds (100 ms, 200 ms, 400 ms)
_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.2, 0.4)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_labels(s3_bucket: str, s3_key: str) -> list[dict[str, Any]]:
    """
    Call AWS Rekognition DetectLabels on an S3 image and return the raw labels.

    Only labels with a confidence score of 70% or higher are returned by
    Rekognition when ``MinConfidence=70`` is specified (Requirement 2.2).
    No further filtering is applied here; callers receive the raw label list
    exactly as Rekognition returns it.

    Retry logic is NOT included in this function — use
    :func:`detect_labels_with_retry` for production calls.

    Args:
        s3_bucket: Name of the S3 bucket that contains the image.
        s3_key:    S3 object key (path) of the image to analyse.

    Returns:
        A list of label dicts as returned by Rekognition.  Each dict contains
        at minimum:

        - ``Name`` (str): Human-readable label name, e.g. ``"Construction Site"``.
        - ``Confidence`` (float): Confidence score in the range 70.0–100.0.

        Additional keys (``Instances``, ``Parents``, ``Aliases``, ``Categories``)
        may also be present depending on the Rekognition API version.

    Raises:
        botocore.exceptions.ClientError: Propagated directly to the caller so
            that retry / dead-letter logic can be applied at a higher level.
    """
    client = boto3.client("rekognition", region_name=AWS_REGION)

    response = client.detect_labels(
        Image={
            "S3Object": {
                "Bucket": s3_bucket,
                "Name": s3_key,
            }
        },
        MinConfidence=70,
    )

    return response["Labels"]


def detect_labels_with_retry(
    s3_bucket: str,
    s3_key: str,
    *,
    _sleep: Any = time.sleep,
) -> list[dict[str, Any]]:
    """
    Call Rekognition DetectLabels with up to 3 retries on transient errors.

    Retries are attempted with exponential backoff delays of 100 ms, 200 ms,
    and 400 ms between successive attempts (Requirement 2.6).  Only transient
    errors (throttling, service unavailable, internal server errors) trigger a
    retry.  Permanent errors such as ``InvalidS3ObjectException`` or
    ``InvalidImageFormatException`` are raised immediately without retrying.

    After all 3 retry attempts are exhausted the final exception is re-raised
    so the Lambda handler adds the SQS record to ``batchItemFailures``, which
    causes SQS to dead-letter the message to ``tagging-dlq``.

    Args:
        s3_bucket: Name of the S3 bucket that contains the image.
        s3_key:    S3 object key (path) of the image to analyse.
        _sleep:    Callable used to introduce delays between retries.  Exposed
                   as a keyword-only parameter to allow tests to inject a no-op
                   without patching ``time.sleep`` globally.

    Returns:
        A list of label dicts as returned by Rekognition (same shape as
        :func:`detect_labels`).

    Raises:
        botocore.exceptions.ClientError: Re-raised after all retry attempts are
            exhausted, or immediately for permanent (non-transient) errors.
        Exception: Any unexpected non-ClientError exception is re-raised
            immediately without retrying.
    """
    last_exc: Exception | None = None

    for attempt, delay in enumerate(_RETRY_DELAYS, start=1):
        try:
            return detect_labels(s3_bucket, s3_key)
        except ClientError as exc:
            error_code: str = exc.response.get("Error", {}).get("Code", "")

            if error_code not in _TRANSIENT_ERROR_CODES:
                # Permanent error — do not retry, raise immediately.
                logger.error(
                    "Rekognition permanent error — not retrying",
                    extra={
                        "attempt": attempt,
                        "error_code": error_code,
                        "s3_bucket": s3_bucket,
                        "s3_key": s3_key,
                    },
                )
                raise

            last_exc = exc
            logger.warning(
                "Rekognition transient error — will retry",
                extra={
                    "attempt": attempt,
                    "error_code": error_code,
                    "delay_seconds": delay,
                    "s3_bucket": s3_bucket,
                    "s3_key": s3_key,
                },
            )
            _sleep(delay)

    # Final attempt (attempt 4 — no delay after this one)
    try:
        return detect_labels(s3_bucket, s3_key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        logger.error(
            "Rekognition call failed after all retry attempts — raising to trigger dead-lettering",
            extra={
                "attempt": len(_RETRY_DELAYS) + 1,
                "error_code": error_code,
                "s3_bucket": s3_bucket,
                "s3_key": s3_key,
            },
        )
        raise
