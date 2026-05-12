"""
Search core adapter — delegates to the root-level VectorStore (vector_store.py).

The VectorStore performs a k-NN cosine similarity search against the
``images`` OpenSearch index populated by the ingestion pipeline.

Environment variables:
  OPENSEARCH_ENDPOINT   OpenSearch Serverless collection endpoint URL
  AWS_REGION            AWS region (default: us-east-1)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup — allow importing the root-level vector_store.py
# ---------------------------------------------------------------------------

_PROJECT_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


class SearchCoreError(Exception):
    """Raised when the search core returns an unexpected error."""


# ---------------------------------------------------------------------------
# Lazy-initialised VectorStore singleton
# ---------------------------------------------------------------------------

_vector_store = None


def _get_vector_store():
    """Return a shared VectorStore instance (created on first call)."""
    global _vector_store
    if _vector_store is None:
        try:
            from vector_store import VectorStore  # type: ignore  # root-level module
            _vector_store = VectorStore()
            logger.info(
                "VectorStore initialised (endpoint=%s)",
                os.getenv("OPENSEARCH_ENDPOINT", "<not set>"),
            )
        except Exception as exc:
            logger.error("Failed to initialise VectorStore: %s", exc)
            raise SearchCoreError(f"Vector store unavailable: {exc}") from exc
    return _vector_store


# ---------------------------------------------------------------------------
# Public interface used by the route handler
# ---------------------------------------------------------------------------

async def run_similarity_search(
    embedding: List[float],
    top_k: int,
    project_id: Optional[str],
    request_id: str,
) -> List[dict]:
    """
    Embed → ANN search via the root VectorStore.

    Delegates to ``VectorStore.search_by_embedding()``, which accepts an
    optional ``filters`` dict for project-level pre-filtering.

    Returns:
        List of dicts with keys ``image_id`` (str) and ``similarity_score`` (float).

    Raises:
        SearchCoreError: if the vector store raises any exception.
    """
    # Build an optional project filter in the format VectorStore expects
    filters: Optional[dict] = None
    if project_id:
        filters = {"term": {"project_id": project_id}}

    try:
        # search_by_embedding is synchronous (opensearch-py uses blocking HTTP).
        # Run it in the default thread pool so we don't block the event loop.
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: _get_vector_store().search_by_embedding(
                embedding, top_k=top_k, filters=filters
            ),
        )
    except SearchCoreError:
        raise
    except Exception as exc:
        logger.error(
            "VectorStore.search_by_embedding raised: %s",
            exc,
            extra={"request_id": request_id},
        )
        raise SearchCoreError(str(exc)) from exc

    # Normalise field names: VectorStore returns "score", route expects "similarity_score"
    results = [
        {
            "image_id": r["image_id"],
            "similarity_score": round(float(r.get("score") or 0.0), 4),
        }
        for r in raw
    ]

    logger.debug(
        "Search core returned %d results",
        len(results),
        extra={"request_id": request_id},
    )
    return results
