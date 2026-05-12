"""
bedrock.py — Bedrock embedding utilities for the Search Handler Lambda.

Provides `embed_query_text` to convert a natural-language query string into a
1024-dimensional float vector using the Amazon Titan Multimodal Embeddings model
(text-input mode).  All Bedrock failures are surfaced as `BedrockUnavailableError`
so the caller can map them to an HTTP 503 response.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MODEL_ID: str = "amazon.titan-embed-image-v1"
_EXPECTED_DIMENSIONS: int = 1024


# ---------------------------------------------------------------------------
# Typed error
# ---------------------------------------------------------------------------


class BedrockUnavailableError(Exception):
    """Raised when the Bedrock Runtime service cannot be reached or returns an
    error, allowing the Lambda handler to return HTTP 503 to the caller.

    Attributes:
        message: Human-readable description of the failure.
        cause: The underlying exception that triggered this error, if any.
    """

    def __init__(self, message: str, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.cause = cause


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_query_text(query: str) -> list[float]:
    """Embed a natural-language query string using Amazon Titan Multimodal
    Embeddings (text-input mode) and return the resulting vector.

    The function creates a fresh Bedrock Runtime boto3 client on every call,
    using the ``AWS_REGION`` environment variable to select the AWS region.
    This keeps the module stateless and easy to test with mocked clients.

    Args:
        query: The natural-language search query to embed.  Must be a
            non-empty string.

    Returns:
        A list of 1024 floats representing the semantic embedding of *query*.

    Raises:
        ValueError: If *query* is empty or not a string.
        BedrockUnavailableError: If the Bedrock Runtime service returns a
            ``ClientError``, if the response cannot be parsed, or if the
            returned embedding does not have exactly 1024 dimensions.

    Example::

        vector = embed_query_text("foundation cracks near column B4")
        assert len(vector) == 1024
    """
    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")

    # ------------------------------------------------------------------
    # Build client
    # ------------------------------------------------------------------
    region: str = os.environ.get("AWS_REGION", "us-east-1")
    logger.debug("Creating Bedrock Runtime client in region %s", region)

    try:
        client = boto3.client("bedrock-runtime", region_name=region)
    except Exception as exc:  # pragma: no cover — boto3 client creation rarely fails
        logger.error("Failed to create Bedrock Runtime client: %s", exc)
        raise BedrockUnavailableError(
            f"Could not create Bedrock Runtime client: {exc}", cause=exc
        ) from exc

    # ------------------------------------------------------------------
    # Invoke model
    # ------------------------------------------------------------------
    request_body: dict[str, Any] = {"inputText": query}
    encoded_body: str = json.dumps(request_body)

    logger.info(
        "Invoking Bedrock model %s for text embedding (query length=%d)",
        _MODEL_ID,
        len(query),
    )

    try:
        response = client.invoke_model(
            modelId=_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=encoded_body,
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "Unknown")
        logger.error(
            "Bedrock ClientError invoking %s: %s — %s",
            _MODEL_ID,
            error_code,
            exc,
        )
        raise BedrockUnavailableError(
            f"Bedrock service error ({error_code}) while embedding query", cause=exc
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error invoking Bedrock model %s: %s", _MODEL_ID, exc)
        raise BedrockUnavailableError(
            f"Unexpected error while calling Bedrock: {exc}", cause=exc
        ) from exc

    # ------------------------------------------------------------------
    # Parse response
    # ------------------------------------------------------------------
    try:
        response_body: dict[str, Any] = json.loads(response["body"].read())
        embedding: list[float] = response_body["embedding"]
    except (KeyError, json.JSONDecodeError, AttributeError) as exc:
        logger.error("Failed to parse Bedrock response: %s", exc)
        raise BedrockUnavailableError(
            f"Could not parse embedding from Bedrock response: {exc}", cause=exc
        ) from exc

    # ------------------------------------------------------------------
    # Dimension validation
    # ------------------------------------------------------------------
    if len(embedding) != _EXPECTED_DIMENSIONS:
        logger.error(
            "Bedrock returned embedding with %d dimensions; expected %d",
            len(embedding),
            _EXPECTED_DIMENSIONS,
        )
        raise BedrockUnavailableError(
            f"Embedding dimension mismatch: got {len(embedding)}, "
            f"expected {_EXPECTED_DIMENSIONS}"
        )

    logger.info(
        "Successfully obtained %d-dimensional embedding from Bedrock", len(embedding)
    )
    return embedding
