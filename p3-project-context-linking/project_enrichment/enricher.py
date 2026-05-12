"""
enricher.py — Enriches search results with project context from the NPC Project API.

Batch-fetches project metadata (name, document count, last-updated) for each
unique project_id in the results list, caching responses to avoid duplicate
API calls within the same batch.

Requirements: 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

import logging
from typing import Any

from project_enrichment.npc_client import get_project_context

logger = logging.getLogger(__name__)

_NULL_CONTEXT: dict[str, Any] = {
    "project_name": None,
    "document_count": None,
    "last_updated": None,
}


def enrich_results(
    results: list[dict[str, Any]],
    npc_api_base_url: str,
) -> list[dict[str, Any]]:
    """Enrich a list of search results with project context from the NPC Project API.

    For each result that contains a ``project_id``, this function fetches the
    corresponding project metadata and merges ``project_name``,
    ``document_count``, and ``last_updated`` into the result dict.

    Responses are cached per ``project_id`` within the batch so that multiple
    results sharing the same project only trigger a single API call.

    If the NPC API returns an error for a given project, the three context
    fields are set to ``None`` and a warning is logged.  The result is never
    dropped.

    Parameters
    ----------
    results:
        List of search result dicts.  Each should contain a ``project_id`` key.
    npc_api_base_url:
        Base URL of the NPC Project API
        (e.g. ``https://api.npc.internal``).

    Returns
    -------
    list[dict]
        The same results list with project context fields merged in.
    """
    if not results:
        return results

    # Cache: project_id -> context dict (or _NULL_CONTEXT on failure)
    context_cache: dict[str, dict[str, Any]] = {}

    for result in results:
        project_id: str | None = result.get("project_id")

        if not project_id:
            # No project_id present — set fields to null
            result.update(_NULL_CONTEXT)
            continue

        # Check cache first
        if project_id not in context_cache:
            context = get_project_context(project_id, npc_api_base_url)
            if context is None:
                logger.warning(
                    "Failed to fetch project context for project_id=%s; "
                    "setting context fields to null",
                    project_id,
                )
                context_cache[project_id] = _NULL_CONTEXT
            else:
                context_cache[project_id] = context

        result.update(context_cache[project_id])

    return results
