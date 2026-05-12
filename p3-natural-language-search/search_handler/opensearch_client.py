"""
opensearch_client.py — OpenSearch ANN search execution for the Search Handler Lambda.

Provides ``run_ann_search`` which submits a pre-built kNN query dict to the
``image-embeddings`` OpenSearch Serverless index and maps the raw hits to the
canonical result schema used by the handler.

All OpenSearch connectivity failures are surfaced as ``OpenSearchUnavailableError``
so the Lambda handler can return HTTP 503 to the caller.

Requirements: 5.2, 5.3, 5.6
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INDEX_NAME: str = "image-embeddings"


# ---------------------------------------------------------------------------
# Typed error
# ---------------------------------------------------------------------------


class OpenSearchUnavailableError(Exception):
    """Raised when the OpenSearch service cannot be reached or returns a
    connection-level error, allowing the Lambda handler to return HTTP 503.

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


def run_ann_search(query: dict[str, Any], os_client: Any) -> list[dict[str, Any]]:
    """Execute an ANN kNN search against the ``image-embeddings`` index and
    return a list of result dicts in the canonical schema.

    The *query* argument should be a complete OpenSearch query body as produced
    by :func:`search_handler.query_builder.build_knn_query`.  The *os_client*
    argument should be an ``opensearch-py`` ``OpenSearch`` instance (or any
    object that exposes a compatible ``.search(index, body)`` method).

    Parameters
    ----------
    query:
        A complete OpenSearch query body dict, e.g. the output of
        ``build_knn_query(vector, k, filters)``.
    os_client:
        An ``opensearch-py`` ``OpenSearch`` client (or compatible mock).

    Returns
    -------
    list[dict]
        A list of result dicts, each containing:

        ``image_id`` (str)
            The document ``_id`` from the OpenSearch hit.
        ``project_id`` (str)
            The ``project_id`` field from the document source.
        ``s3_url`` (str)
            The ``s3_url`` field from the document source.
        ``tags`` (list[str])
            The ``tags`` field from the document source (defaults to ``[]``).
        ``date`` (str | None)
            The ``date`` field from the document source.
        ``location`` (str | None)
            The ``location`` field from the document source.
        ``relevance_score`` (float)
            The hit ``_score`` clamped to the range [0.0, 1.0].

        Returns an empty list when the index contains zero matching hits.

    Raises
    ------
    OpenSearchUnavailableError
        If the OpenSearch client raises a connection-level or transport error.

    Example::

        from opensearchpy import OpenSearch
        from search_handler.query_builder import build_knn_query
        from search_handler.opensearch_client import run_ann_search

        os_client = OpenSearch(hosts=[{"host": endpoint, "port": 443}], ...)
        query = build_knn_query(vector, k=20, filters={"project_id": "PROJ-001"})
        results = run_ann_search(query, os_client)
        for r in results:
            print(r["image_id"], r["relevance_score"])
    """
    logger.info(
        "Executing ANN search on index '%s' (query size=%s)",
        _INDEX_NAME,
        query.get("size"),
    )

    # ------------------------------------------------------------------
    # Execute search
    # ------------------------------------------------------------------
    try:
        response = os_client.search(index=_INDEX_NAME, body=query)
    except Exception as exc:
        logger.error(
            "OpenSearch search call failed on index '%s': %s", _INDEX_NAME, exc
        )
        raise OpenSearchUnavailableError(
            f"OpenSearch search failed: {exc}", cause=exc
        ) from exc

    # ------------------------------------------------------------------
    # Parse hits
    # ------------------------------------------------------------------
    try:
        hits_wrapper = response.get("hits", {})
        total_value: int = (
            hits_wrapper.get("total", {}).get("value", 0)
            if isinstance(hits_wrapper.get("total"), dict)
            else int(hits_wrapper.get("total", 0))
        )
        hits: list[dict[str, Any]] = hits_wrapper.get("hits", [])
    except (AttributeError, TypeError) as exc:
        logger.error("Failed to parse OpenSearch response structure: %s", exc)
        raise OpenSearchUnavailableError(
            f"Unexpected OpenSearch response format: {exc}", cause=exc
        ) from exc

    if total_value == 0 or not hits:
        logger.info("ANN search returned zero hits for index '%s'", _INDEX_NAME)
        return []

    # ------------------------------------------------------------------
    # Map hits to result schema
    # ------------------------------------------------------------------
    results: list[dict[str, Any]] = []
    for hit in hits:
        source: dict[str, Any] = hit.get("_source", {})
        raw_score: float = float(hit.get("_score") or 0.0)

        # Clamp relevance_score to [0.0, 1.0]
        relevance_score: float = min(max(raw_score, 0.0), 1.0)

        result: dict[str, Any] = {
            "image_id": hit.get("_id", ""),
            "project_id": source.get("project_id", ""),
            "s3_url": source.get("s3_url", ""),
            "tags": source.get("tags", []),
            "date": source.get("date"),
            "location": source.get("location"),
            "relevance_score": relevance_score,
        }
        results.append(result)

    logger.info(
        "ANN search returned %d result(s) from index '%s'",
        len(results),
        _INDEX_NAME,
    )
    return results
