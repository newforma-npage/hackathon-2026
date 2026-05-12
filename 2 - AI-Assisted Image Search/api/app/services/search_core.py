"""
Search core adapter — thin wrapper around the shared t9 search module (P3).

HOW TO INTEGRATE WITH P3's MODULE
----------------------------------
When the P3 participant delivers their search core, replace the stub below
with a real import.  The contract this adapter expects:

    from <p3_module> import run_ann_search

    async def run_ann_search(
        embedding: List[float],
        top_k: int,
        project_id: Optional[str] = None,
    ) -> List[dict]:
        # Returns a list of dicts: [{"image_id": str, "similarity_score": float}, ...]

Until then, the stub returns mock results so the endpoint is fully testable
end-to-end without the P3 dependency.
"""

from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class SearchCoreError(Exception):
    """Raised when the search core returns an unexpected error."""


# ---------------------------------------------------------------------------
# Stub — replace the body of _call_search_core with the real P3 import
# ---------------------------------------------------------------------------

async def _call_search_core(
    embedding: List[float],
    top_k: int,
    project_id: Optional[str],
) -> List[dict]:
    """
    STUB: simulates the P3 search core response.

    Replace this function body with the real call once P3 is available:

        from search_core import run_ann_search   # P3 module
        return await run_ann_search(embedding, top_k, project_id)
    """
    # Mock: return a handful of fake image IDs with descending scores
    mock_results = [
        {"image_id": f"site-photo-{i:02d}.jpg", "similarity_score": round(0.99 - i * 0.05, 2)}
        for i in range(1, min(top_k, 16) + 1)
    ]
    if project_id:
        # Simulate project filter — only keep IDs that would belong to the project
        # (in the real implementation this is handled inside OpenSearch)
        mock_results = mock_results[:max(1, top_k // 2)]

    return mock_results[:top_k]


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
    Invoke the search core and return raw results.

    Returns:
        List of dicts with keys ``image_id`` (str) and ``similarity_score`` (float).

    Raises:
        SearchCoreError: if the search core raises any exception.
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
