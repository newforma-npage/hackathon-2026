"""
Search core adapter — delegates to the shared OpenSearchVectorStore from
app/backend/vector_store.py.

The vector store performs a k-NN cosine similarity search against the
`visual-project-intelligence` OpenSearch index populated by the ingestion
pipeline (app/backend/main.py + lambda/image_ingestion/handler.py).

Environment variables (same as the ingestion backend):
  OPENSEARCH_HOST       OpenSearch domain endpoint
  OPENSEARCH_USER       HTTP basic auth username  (optional)
  OPENSEARCH_PASS       HTTP basic auth password  (optional)
  VECTOR_INDEX_NAME     Index name (default: visual-project-intelligence)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path setup — allow importing from app/backend without installing as a package
# ---------------------------------------------------------------------------

_BACKEND_DIR = os.path.join(
    os.path.dirname(__file__),          # api/app/services/
    "..", "..", "..",                    # → api/
    "..", "app",                        # → 2 - AI-Assisted Image Search/app/
)
_BACKEND_DIR = os.path.normpath(_BACKEND_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


class SearchCoreError(Exception):
    """Raised when the search core returns an unexpected error."""


# ---------------------------------------------------------------------------
# Lazy-initialised vector store singleton
# ---------------------------------------------------------------------------

_vector_store = None


def _get_vector_store():
    """Return a shared OpenSearchVectorStore instance (created on first call)."""
    global _vector_store
    if _vector_store is None:
        try:
            from backend.vector_store import OpenSearchVectorStore  # type: ignore
            _vector_store = OpenSearchVectorStore()
            logger.info("OpenSearchVectorStore initialised (host=%s)", os.getenv("OPENSEARCH_HOST"))
        except Exception as exc:
            logger.error("Failed to initialise OpenSearchVectorStore: %s", exc)
            raise SearchCoreError(f"Vector store unavailable: {exc}") from exc
    return _vector_store


# ---------------------------------------------------------------------------
# Internal search call
# ---------------------------------------------------------------------------

async def _call_search_core(
    embedding: List[float],
    top_k: int,
    project_id: Optional[str],
) -> List[dict]:
    """
    Delegate to OpenSearchVectorStore.knn_search().

    Returns a list of dicts: [{"image_id": str, "similarity_score": float}, ...]
    """
    try:
        from backend.vector_store import SearchFilters  # type: ignore
    except ImportError as exc:
        raise SearchCoreError(f"Could not import vector_store: {exc}") from exc

    filters = SearchFilters(
        project_ids=[project_id] if project_id else None,
    )

    # knn_search is synchronous (opensearch-py uses blocking HTTP); run it
    # directly — the FastAPI route is already async so this is fine for now.
    # For high-concurrency deployments, wrap in run_in_executor.
    import asyncio
    loop = asyncio.get_event_loop()
    candidates = await loop.run_in_executor(
        None,
        lambda: _get_vector_store().knn_search(embedding, k=top_k, filters=filters),
    )

    return [
        {"image_id": c.photo_id, "similarity_score": round(c.score, 4)}
        for c in candidates
    ]


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
    Invoke the OpenSearch vector store and return raw results.

    Returns:
        List of dicts with keys ``image_id`` (str) and ``similarity_score`` (float).

    Raises:
        SearchCoreError: if the vector store raises any exception.
    """
    try:
        results = await _call_search_core(embedding, top_k, project_id)
        logger.debug(
            "Search core returned %d results",
            len(results),
            extra={"request_id": request_id},
        )
        return results
    except SearchCoreError:
        raise
    except Exception as exc:
        logger.error(
            "Search core raised unexpected error: %s",
            exc,
            extra={"request_id": request_id},
        )
        raise SearchCoreError(str(exc)) from exc
