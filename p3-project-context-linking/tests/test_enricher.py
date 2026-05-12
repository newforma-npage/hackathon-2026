"""
test_enricher.py — Unit tests for the project context enrichment module.

Requirements: 8.1, 8.2, 8.3, 8.4
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
import requests

from project_enrichment.enricher import enrich_results


NPC_BASE_URL = "https://api.npc.internal"


class TestEnrichResults:
    """Tests for enrich_results()."""

    @patch("project_enrichment.npc_client.requests.get")
    def test_valid_project_context_merged_into_results(self, mock_get: MagicMock) -> None:
        """Valid project context fields are merged into each result."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "project_name": "Harbor Bridge",
            "document_count": 42,
            "last_updated": "2025-06-01T12:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = [
            {"project_id": "PROJ-001", "photo_id": "img-1"},
            {"project_id": "PROJ-001", "photo_id": "img-2"},
        ]

        enriched = enrich_results(results, NPC_BASE_URL)

        assert len(enriched) == 2
        for r in enriched:
            assert r["project_name"] == "Harbor Bridge"
            assert r["document_count"] == 42
            assert r["last_updated"] == "2025-06-01T12:00:00Z"

    @patch("project_enrichment.npc_client.requests.get")
    def test_same_project_id_only_one_api_call(self, mock_get: MagicMock) -> None:
        """Multiple results with the same project_id trigger only one API call (caching)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "project_name": "Tower Project",
            "document_count": 10,
            "last_updated": "2025-05-15T08:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = [
            {"project_id": "PROJ-002", "photo_id": "img-a"},
            {"project_id": "PROJ-002", "photo_id": "img-b"},
            {"project_id": "PROJ-002", "photo_id": "img-c"},
        ]

        enrich_results(results, NPC_BASE_URL)

        # Only one HTTP call should have been made
        mock_get.assert_called_once()

    @patch("project_enrichment.npc_client.requests.get")
    def test_npc_api_404_sets_fields_to_null(self, mock_get: MagicMock) -> None:
        """NPC API returning 404 sets context fields to null; result is not dropped."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Not Found"
        )
        mock_get.return_value = mock_response

        results = [{"project_id": "PROJ-MISSING", "photo_id": "img-x"}]

        enriched = enrich_results(results, NPC_BASE_URL)

        assert len(enriched) == 1
        assert enriched[0]["project_name"] is None
        assert enriched[0]["document_count"] is None
        assert enriched[0]["last_updated"] is None
        # Original fields preserved
        assert enriched[0]["photo_id"] == "img-x"

    @patch("project_enrichment.npc_client.requests.get")
    def test_npc_api_timeout_sets_fields_to_null(self, mock_get: MagicMock) -> None:
        """NPC API timeout sets context fields to null; result is not dropped."""
        mock_get.side_effect = requests.exceptions.Timeout("Connection timed out")

        results = [{"project_id": "PROJ-SLOW", "photo_id": "img-y"}]

        enriched = enrich_results(results, NPC_BASE_URL)

        assert len(enriched) == 1
        assert enriched[0]["project_name"] is None
        assert enriched[0]["document_count"] is None
        assert enriched[0]["last_updated"] is None
        assert enriched[0]["photo_id"] == "img-y"

    def test_empty_results_returns_empty_list(self) -> None:
        """Empty results list returns empty list without any API calls."""
        enriched = enrich_results([], NPC_BASE_URL)
        assert enriched == []

    @patch("project_enrichment.npc_client.requests.get")
    def test_results_with_no_project_id_sets_fields_to_null(
        self, mock_get: MagicMock
    ) -> None:
        """Results missing project_id get context fields set to null."""
        results = [
            {"photo_id": "img-orphan"},
            {"project_id": None, "photo_id": "img-null-pid"},
        ]

        enriched = enrich_results(results, NPC_BASE_URL)

        assert len(enriched) == 2
        for r in enriched:
            assert r["project_name"] is None
            assert r["document_count"] is None
            assert r["last_updated"] is None

        # No API calls should have been made
        mock_get.assert_not_called()

    @patch("project_enrichment.npc_client.requests.get")
    def test_mixed_success_and_failure(self, mock_get: MagicMock) -> None:
        """Mix of successful and failed project lookups enriches correctly."""

        def side_effect(url: str, timeout: float) -> MagicMock:
            if "PROJ-OK" in url:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "project_name": "Good Project",
                    "document_count": 5,
                    "last_updated": "2025-01-01T00:00:00Z",
                }
                resp.raise_for_status = MagicMock()
                return resp
            else:
                resp = MagicMock()
                resp.status_code = 500
                resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
                    "500 Server Error"
                )
                return resp

        mock_get.side_effect = side_effect

        results = [
            {"project_id": "PROJ-OK", "photo_id": "img-1"},
            {"project_id": "PROJ-FAIL", "photo_id": "img-2"},
        ]

        enriched = enrich_results(results, NPC_BASE_URL)

        assert enriched[0]["project_name"] == "Good Project"
        assert enriched[0]["document_count"] == 5
        assert enriched[1]["project_name"] is None
        assert enriched[1]["document_count"] is None
