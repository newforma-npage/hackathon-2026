"""
Bedrock Titan Multimodal Embeddings client.

Model: amazon.titan-embed-image-v1
- Accepts image bytes, text, or both (multimodal)
- Always returns a 1024-dimension vector
  (Titan Multimodal v1 outputs 1024 dims; design doc targets 1536 which maps
   to Titan Text Embeddings v2 — this module supports both and normalises the
   dimension constant so the rest of the codebase stays model-agnostic)

Ref: https://docs.aws.amazon.com/bedrock/latest/userguide/titan-multimodal-embeddings.html
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

# ── Constants ─────────────────────────────────────────────────────────────────

# Titan Multimodal Embeddings v1 — supports image + text input
MULTIMODAL_MODEL_ID = "amazon.titan-embed-image-v1"

# Titan Text Embeddings v2 — text-only, 1536 dims (matches design doc spec)
TEXT_MODEL_ID = "amazon.titan-embed-text-v2:0"

# Dimension produced by each model
MULTIMODAL_EMBEDDING_DIM = 1024   # Titan Multimodal v1
TEXT_EMBEDDING_DIM = 1536         # Titan Text v2

# Active model version tag stored alongside each vector for reconciliation
CURRENT_MODEL_VERSION = 1

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


# ── Client ────────────────────────────────────────────────────────────────────

class BedrockEmbeddingClient:
    """
    Wraps AWS Bedrock InvokeModel calls for Titan Multimodal and Text embeddings.

    Usage
    -----
    client = BedrockEmbeddingClient()

    # Embed an image (returns 1024-dim vector)
    vector = client.embed_image(image_bytes)

    # Embed a text query (returns 1536-dim vector)
    vector = client.embed_text("foundation cracks")

    # Embed image + text together (multimodal, returns 1024-dim vector)
    vector = client.embed_multimodal(image_bytes=img, text="steel beam")
    """

    def __init__(self, region: str = AWS_REGION):
        self._client = boto3.client("bedrock-runtime", region_name=region)

    # ── Public API ────────────────────────────────────────────────────────────

    def embed_image(self, image_bytes: bytes) -> list[float]:
        """
        Generate a 1024-dim embedding from raw image bytes using
        Titan Multimodal Embeddings v1.

        Parameters
        ----------
        image_bytes : bytes
            Raw JPEG/PNG image data.

        Returns
        -------
        list[float]
            1024-dimension embedding vector.

        Raises
        ------
        ValueError
            If the returned vector does not have the expected dimension.
        ClientError
            On AWS API errors.
        """
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        payload = {"inputImage": b64_image}
        return self._invoke_multimodal(payload, expected_dim=MULTIMODAL_EMBEDDING_DIM)

    def embed_text(self, text: str) -> list[float]:
        """
        Generate a 1536-dim embedding from a text string using
        Titan Text Embeddings v2.

        Parameters
        ----------
        text : str
            Natural language query or description (max ~8192 tokens).

        Returns
        -------
        list[float]
            1536-dimension embedding vector.

        Raises
        ------
        ValueError
            If the returned vector does not have the expected dimension.
        ClientError
            On AWS API errors.
        """
        payload = {"inputText": text}
        body = json.dumps(payload)
        response = self._client.invoke_model(
            modelId=TEXT_MODEL_ID,
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        vector = result["embedding"]
        self._assert_dim(vector, TEXT_EMBEDDING_DIM, "text")
        return vector

    def embed_multimodal(
        self,
        image_bytes: Optional[bytes] = None,
        text: Optional[str] = None,
    ) -> list[float]:
        """
        Generate a 1024-dim embedding from an image, text, or both.
        At least one of image_bytes or text must be provided.

        Parameters
        ----------
        image_bytes : bytes, optional
            Raw JPEG/PNG image data.
        text : str, optional
            Accompanying text description or query.

        Returns
        -------
        list[float]
            1024-dimension multimodal embedding vector.
        """
        if image_bytes is None and text is None:
            raise ValueError("At least one of image_bytes or text must be provided.")

        payload: dict = {}
        if image_bytes is not None:
            payload["inputImage"] = base64.b64encode(image_bytes).decode("utf-8")
        if text is not None:
            payload["inputText"] = text

        return self._invoke_multimodal(payload, expected_dim=MULTIMODAL_EMBEDDING_DIM)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _invoke_multimodal(self, payload: dict, expected_dim: int) -> list[float]:
        body = json.dumps(payload)
        try:
            response = self._client.invoke_model(
                modelId=MULTIMODAL_MODEL_ID,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
        except ClientError as exc:
            raise RuntimeError(
                f"Bedrock InvokeModel failed for {MULTIMODAL_MODEL_ID}: {exc}"
            ) from exc

        result = json.loads(response["body"].read())
        vector = result["embedding"]
        self._assert_dim(vector, expected_dim, "multimodal")
        return vector

    @staticmethod
    def _assert_dim(vector: list, expected: int, label: str) -> None:
        if len(vector) != expected:
            raise ValueError(
                f"Bedrock {label} embedding returned {len(vector)} dimensions; "
                f"expected {expected}."
            )
