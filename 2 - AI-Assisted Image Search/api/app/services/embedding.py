"""
Embedding service — converts raw image bytes to a vector using AWS Bedrock.

Model used: amazon.titan-embed-image-v1
This must match the model used by P1 (ingest/index) so vectors are comparable.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import List

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — keep in sync with P1's indexing config
# ---------------------------------------------------------------------------

BEDROCK_MODEL_ID = "amazon.titan-embed-image-v1"
EMBEDDING_DIMENSIONS = 1024          # Titan image embedding output size
BEDROCK_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
BACKOFF_BASE_MS = 200                # 200 ms → 400 ms → 800 ms

# Retryable Bedrock error codes
_RETRYABLE_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
}


class EmbeddingError(Exception):
    """Raised when Bedrock embedding fails after all retries."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _is_retryable(error: ClientError) -> bool:
    return error.response["Error"]["Code"] in _RETRYABLE_CODES


async def embed_image(image_bytes: bytes, request_id: str) -> List[float]:
    """
    Embed *image_bytes* via Bedrock and return the embedding vector.

    Raises:
        EmbeddingError: with code EMBEDDING_FAILED or EMBEDDING_TIMEOUT.
    """
    client = boto3.client("bedrock-runtime")

    payload = {
        "inputImage": base64.b64encode(image_bytes).decode("utf-8"),
        "embeddingConfig": {"outputEmbeddingLength": EMBEDDING_DIMENSIONS},
    }

    attempt = 0
    delay_ms = BACKOFF_BASE_MS

    while attempt <= MAX_RETRIES:
        try:
            logger.debug(
                "Bedrock embed attempt %d/%d",
                attempt + 1,
                MAX_RETRIES + 1,
                extra={"request_id": request_id},
            )

            # Run the blocking boto3 call in a thread pool so we don't block
            # the async event loop, and enforce the timeout.
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: client.invoke_model(
                        modelId=BEDROCK_MODEL_ID,
                        contentType="application/json",
                        accept="application/json",
                        body=json.dumps(payload),
                    ),
                ),
                timeout=BEDROCK_TIMEOUT_SECONDS,
            )

            body = json.loads(response["body"].read())
            embedding: List[float] = body["embedding"]

            if len(embedding) != EMBEDDING_DIMENSIONS:
                raise EmbeddingError(
                    "EMBEDDING_FAILED",
                    f"Unexpected embedding length {len(embedding)}, expected {EMBEDDING_DIMENSIONS}.",
                )

            return embedding

        except asyncio.TimeoutError:
            logger.error(
                "Bedrock call timed out after %ds",
                BEDROCK_TIMEOUT_SECONDS,
                extra={"request_id": request_id},
            )
            raise EmbeddingError(
                "EMBEDDING_TIMEOUT",
                f"Bedrock did not respond within {BEDROCK_TIMEOUT_SECONDS} seconds.",
            )

        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if _is_retryable(exc) and attempt < MAX_RETRIES:
                logger.warning(
                    "Retryable Bedrock error %s on attempt %d, retrying in %dms",
                    code,
                    attempt + 1,
                    delay_ms,
                    extra={"request_id": request_id},
                )
                await asyncio.sleep(delay_ms / 1000)
                delay_ms = min(delay_ms * 2, 1600)
                attempt += 1
                continue

            # Non-retryable or retries exhausted
            logger.error(
                "Bedrock error %s: %s",
                code,
                exc.response["Error"]["Message"],
                extra={"request_id": request_id},
            )
            raise EmbeddingError(
                "EMBEDDING_FAILED",
                f"Bedrock embedding failed: {exc.response['Error']['Message']}",
            )

    # Should not be reached, but satisfies type checker
    raise EmbeddingError("EMBEDDING_FAILED", "Embedding failed after all retries.")
