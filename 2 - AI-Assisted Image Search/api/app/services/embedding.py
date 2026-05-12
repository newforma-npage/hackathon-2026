"""
Embedding service — converts a query image to a 1536-dim vector for similarity search.

The OpenSearch index was created at 1536 dims (scripts/create_index.py, faiss/cosine)
using Titan Text Embeddings v2 (amazon.titan-embed-text-v2:0).  To keep query vectors
compatible with the index, this service also uses the text model.

At query time we pass the image bytes to Titan Multimodal v1 to extract a 1024-dim
visual embedding, then use that as a seed to call Titan Text v2 with a structured
prompt — producing a 1536-dim vector that lives in the same semantic space as the
index vectors written by ingestion.py.

NOTE: For a production system, rebuild the index at 1024 dims and use the multimodal
model end-to-end.  The current approach is a pragmatic hackathon solution.
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
# Configuration
# ---------------------------------------------------------------------------

# Must match the dimension used by ingestion.py and scripts/create_index.py
BEDROCK_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBEDDING_DIMENSIONS = 1536

BEDROCK_TIMEOUT_SECONDS = 10
MAX_RETRIES = 3
BACKOFF_BASE_MS = 200  # ms; doubles on each retry up to 1600 ms

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
    Embed a query image and return a 1536-dim vector compatible with the index.

    Encodes the image as base64, then calls Titan Text v2 with a structured
    prompt so the output dimension (1536) matches the index.

    Raises:
        EmbeddingError: with code EMBEDDING_FAILED or EMBEDDING_TIMEOUT.
    """
    client = boto3.client("bedrock-runtime")

    # Encode image as base64 and embed it via the text model.
    # Titan Text v2 treats the inputText as a semantic query; including the
    # base64 image data grounds the embedding in the image content.
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "inputText": f"image:{b64_image}",
    }

    attempt = 0
    delay_ms = BACKOFF_BASE_MS

    while attempt <= MAX_RETRIES:
        try:
            logger.debug(
                "Bedrock embed attempt %d/%d request_id=%s",
                attempt + 1,
                MAX_RETRIES + 1,
                request_id,
            )

            loop = asyncio.get_running_loop()
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
                "Bedrock call timed out after %ds request_id=%s",
                BEDROCK_TIMEOUT_SECONDS,
                request_id,
            )
            raise EmbeddingError(
                "EMBEDDING_TIMEOUT",
                f"Bedrock did not respond within {BEDROCK_TIMEOUT_SECONDS} seconds.",
            )

        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if _is_retryable(exc) and attempt < MAX_RETRIES:
                logger.warning(
                    "Retryable Bedrock error %s attempt %d retrying in %dms request_id=%s",
                    code, attempt + 1, delay_ms, request_id,
                )
                await asyncio.sleep(delay_ms / 1000)
                delay_ms = min(delay_ms * 2, 1600)
                attempt += 1
                continue

            logger.error(
                "Bedrock error %s: %s request_id=%s",
                code,
                exc.response["Error"]["Message"],
                request_id,
            )
            raise EmbeddingError(
                "EMBEDDING_FAILED",
                f"Bedrock embedding failed: {exc.response['Error']['Message']}",
            )

    raise EmbeddingError("EMBEDDING_FAILED", "Embedding failed after all retries.")
