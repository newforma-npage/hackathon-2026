"""
Ingest → Embed → Index pipeline.

This module is the single authoritative entry point for processing a project
image end-to-end:

    1. Rekognition DetectLabels + DetectModerationLabels  (labeling.py)
    2. Bedrock Titan Multimodal Embeddings                (embeddings.py)
    3. Write vector + tags to OpenSearch                  (vector_store.py / root)

Design decisions
----------------
* Uses the root-level ``vector_store.VectorStore`` (1536-dim, faiss/cosine)
  so the index is compatible with the search API (api/app/services/search_core.py)
  and the existing property-based tests (tests/test_vector_store_pbt.py).
* The Bedrock multimodal model (amazon.titan-embed-image-v1) outputs 1024 dims.
  To write into the 1536-dim index we use the text model
  (amazon.titan-embed-text-v2:0) on the AI description produced by Rekognition.
  This keeps the index schema consistent while still grounding the vector in
  the visual content of the image.
* All three steps are executed synchronously.  The caller (FastAPI route or
  Lambda) is responsible for running this in a thread pool if needed.

Usage
-----
    from app.backend.ingestion import IngestionPipeline, IngestionResult

    pipeline = IngestionPipeline()
    result   = pipeline.ingest(
        photo_id   = "abc-123",
        project_id = "PROJ-001",
        filename   = "site-photo-01.jpg",
        image_bytes = open("site-photo-01.jpg", "rb").read(),
        metadata   = {
            "project_name": "Harbor Bridge Reconstruction",
            "location":     "Pier P-3, East Side",
            "date_taken":   "2024-04-15T08:30:00-07:00",
            "taken_by":     "John Smith",
        },
    )

    result.photo_id          # str
    result.ai_labels         # list[str]  — slugs
    result.ai_description    # str
    result.embedding_dim     # int  — 1536
    result.opensearch_result # dict — raw OpenSearch index response
    result.is_flagged        # bool — True if moderation labels found
"""

from __future__ import annotations

import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup — add the project root (2 - AI-Assisted Image Search/) to
# sys.path so we can import the root-level vector_store.py.
# Uses Path(__file__).resolve() so this works regardless of cwd.
# ---------------------------------------------------------------------------
from pathlib import Path as _Path

_PROJECT_ROOT = str(_Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Local imports
# ---------------------------------------------------------------------------
from .embeddings import BedrockEmbeddingClient, TEXT_EMBEDDING_DIM  # noqa: E402
from .labeling import RekognitionLabeler, LabelingResult             # noqa: E402


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class IngestionResult:
    """
    The complete output of one ingest → embed → index run.

    Attributes
    ----------
    photo_id : str
        The document ID written to OpenSearch.
    ai_labels : list[str]
        Rekognition label slugs (confidence ≥ 70 %).
    ai_description : str
        Natural-language description built from the top labels.
    ai_tags : list[dict]
        Full structured tag list (name, slug, confidence, category, parents).
    moderation_flags : list[str]
        Any moderation labels detected by Rekognition.
    is_flagged : bool
        True if any moderation labels were detected.
    embedding_dim : int
        Dimension of the vector written to OpenSearch (1536).
    opensearch_result : dict
        Raw response from the OpenSearch index call.
    indexed_at : str
        ISO-8601 UTC timestamp of when indexing completed.
    """
    photo_id:          str
    ai_labels:         list[str]
    ai_description:    str
    ai_tags:           list  # list[Tag] — kept as Tag objects for caller inspection
    moderation_flags:  list[str]
    is_flagged:        bool
    embedding_dim:     int
    opensearch_result: dict
    indexed_at:        str = field(default_factory=lambda: datetime.utcnow().isoformat())


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class IngestionPipeline:
    """
    Orchestrates the ingest → embed → index flow for a single image.

    Parameters
    ----------
    labeler : RekognitionLabeler, optional
        Inject a custom labeler (useful for testing).
    embedder : BedrockEmbeddingClient, optional
        Inject a custom embedding client (useful for testing).
    vector_store : VectorStore-like, optional
        Inject a custom vector store (useful for testing).
        Must expose ``index_image(image_id, project_id, embedding, tags, date, location)``.
    region : str
        AWS region (default: AWS_REGION env var or "us-east-1").
    opensearch_endpoint : str, optional
        OpenSearch endpoint URL.  Falls back to OPENSEARCH_ENDPOINT env var.
    """

    def __init__(
        self,
        labeler: Optional[RekognitionLabeler] = None,
        embedder: Optional[BedrockEmbeddingClient] = None,
        vector_store=None,
        region: Optional[str] = None,
        opensearch_endpoint: Optional[str] = None,
    ) -> None:
        _region = region or os.getenv("AWS_REGION", "us-east-1")

        self._labeler = labeler or RekognitionLabeler(region=_region)
        self._embedder = embedder or BedrockEmbeddingClient(region=_region)
        self._vector_store = vector_store or self._build_vector_store(opensearch_endpoint)

    @staticmethod
    def _build_vector_store(endpoint: Optional[str]):
        """Lazy-import and construct the root-level VectorStore."""
        try:
            from vector_store import VectorStore  # type: ignore
            return VectorStore(endpoint=endpoint)
        except Exception as exc:
            raise RuntimeError(
                f"Could not initialise VectorStore: {exc}. "
                "Set OPENSEARCH_ENDPOINT or pass opensearch_endpoint= to IngestionPipeline."
            ) from exc

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def ingest(
        self,
        photo_id: str,
        project_id: str,
        filename: str,
        image_bytes: bytes,
        metadata: Optional[dict[str, Any]] = None,
    ) -> IngestionResult:
        """
        Run the full ingest → embed → index pipeline for one image.

        Parameters
        ----------
        photo_id : str
            Unique identifier for this image (used as the OpenSearch _id).
        project_id : str
            Project the image belongs to.
        filename : str
            Original filename (e.g. "site-photo-01.jpg").
        image_bytes : bytes
            Raw JPEG or PNG image data.
        metadata : dict, optional
            Additional fields to store alongside the vector:
              project_name, location, date_taken, taken_by.

        Returns
        -------
        IngestionResult

        Raises
        ------
        ValueError
            If the image is flagged for moderation content.
        RuntimeError
            If Rekognition, Bedrock, or OpenSearch calls fail.
        """
        meta = metadata or {}
        logger.info(
            "Ingesting photo_id=%s project_id=%s filename=%s",
            photo_id, project_id, filename,
        )

        # ── Step 1: Rekognition labeling ──────────────────────────────────
        labeling: LabelingResult = self._run_labeling(image_bytes, photo_id)

        if labeling.is_flagged:
            raise ValueError(
                f"Image {filename!r} flagged for moderation: "
                f"{', '.join(labeling.moderation_flags)}"
            )

        # ── Step 2: Bedrock text embedding of the AI description ──────────
        # We embed the AI description (text) rather than the raw image bytes
        # so the vector dimension is 1536 — matching the OpenSearch index
        # created by scripts/create_index.py and used by the search API.
        embedding = self._run_embedding(labeling.description, photo_id)

        # ── Step 3: Write to OpenSearch ───────────────────────────────────
        os_result = self._run_index(
            photo_id=photo_id,
            project_id=project_id,
            embedding=embedding,
            tags=labeling.ai_labels,
            date=meta.get("date_taken", ""),
            location=meta.get("location", ""),
        )

        result = IngestionResult(
            photo_id=photo_id,
            ai_labels=labeling.ai_labels,
            ai_description=labeling.description,
            ai_tags=labeling.tags,          # list[Tag] — kept as objects here
            moderation_flags=labeling.moderation_flags,
            is_flagged=labeling.is_flagged,
            embedding_dim=len(embedding),
            opensearch_result=os_result,
        )

        logger.info(
            "Ingestion complete photo_id=%s labels=%d embedding_dim=%d os_result=%s",
            photo_id, len(labeling.ai_labels), len(embedding),
            os_result.get("result", "?"),
        )
        return result

    # -----------------------------------------------------------------------
    # Private helpers — each wraps one external call with structured logging
    # -----------------------------------------------------------------------

    def _run_labeling(self, image_bytes: bytes, photo_id: str) -> LabelingResult:
        logger.debug("Running Rekognition labeling for photo_id=%s", photo_id)
        try:
            result = self._labeler.label(image_bytes)
            logger.info(
                "Rekognition: photo_id=%s labels=%d flagged=%s",
                photo_id, len(result.tags), result.is_flagged,
            )
            return result
        except Exception as exc:
            logger.error("Rekognition failed for photo_id=%s: %s", photo_id, exc)
            raise RuntimeError(f"Rekognition labeling failed: {exc}") from exc

    def _run_embedding(self, text: str, photo_id: str) -> list[float]:
        logger.debug("Running Bedrock embedding for photo_id=%s", photo_id)
        try:
            vector = self._embedder.embed_text(text)
            logger.info(
                "Bedrock: photo_id=%s embedding_dim=%d", photo_id, len(vector)
            )
            return vector
        except Exception as exc:
            logger.error("Bedrock embedding failed for photo_id=%s: %s", photo_id, exc)
            raise RuntimeError(f"Bedrock embedding failed: {exc}") from exc

    def _run_index(
        self,
        photo_id: str,
        project_id: str,
        embedding: list[float],
        tags: list[str],
        date: str,
        location: str,
    ) -> dict:
        logger.debug("Writing to OpenSearch for photo_id=%s", photo_id)
        try:
            result = self._vector_store.index_image(
                photo_id, project_id, embedding, tags, date, location
            )
            logger.info(
                "OpenSearch: photo_id=%s result=%s",
                photo_id, result.get("result", "?"),
            )
            return result
        except Exception as exc:
            logger.error("OpenSearch index failed for photo_id=%s: %s", photo_id, exc)
            raise RuntimeError(f"OpenSearch indexing failed: {exc}") from exc
