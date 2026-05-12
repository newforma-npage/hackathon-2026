"""
npc_client.py — Thin HTTP client for the NPC Project API.

Provides a single function to fetch project context (name, document count,
last-updated timestamp) for a given project ID.

Requirements: 8.1, 8.2
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS: float = 2.0


def get_project_context(project_id: str, base_url: str) -> dict[str, Any] | None:
    """Fetch project context from the NPC Project API.

    Calls ``GET {base_url}/projects/{project_id}`` and returns the project
    metadata on success.

    Parameters
    ----------
    project_id:
        The unique identifier of the project to look up.
    base_url:
        Base URL of the NPC Project API (e.g. ``https://api.npc.internal``).

    Returns
    -------
    dict | None
        A dict with keys ``project_name``, ``document_count``, and
        ``last_updated`` on success.  Returns ``None`` on any HTTP error
        (4xx, 5xx), timeout, or connection failure.
    """
    url = f"{base_url.rstrip('/')}/projects/{project_id}"

    try:
        response = requests.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return {
            "project_name": data.get("project_name"),
            "document_count": data.get("document_count"),
            "last_updated": data.get("last_updated"),
        }
    except requests.exceptions.Timeout:
        logger.warning(
            "NPC Project API timeout for project_id=%s (url=%s)",
            project_id,
            url,
        )
    except requests.exceptions.ConnectionError:
        logger.warning(
            "NPC Project API connection error for project_id=%s (url=%s)",
            project_id,
            url,
        )
    except requests.exceptions.HTTPError as exc:
        logger.warning(
            "NPC Project API HTTP error for project_id=%s: %s",
            project_id,
            exc,
        )
    except Exception as exc:
        logger.warning(
            "NPC Project API unexpected error for project_id=%s: %s",
            project_id,
            exc,
        )

    return None
