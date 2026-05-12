"""
Unit tests for POST /search/similar.

Run with:  pytest api/tests/ -v  (from the project root)
       or: pytest tests/ -v       (from api/)

These tests mock out Bedrock and the search core so no AWS credentials are needed.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_b64() -> str:
    """Minimal valid JPEG header (3 magic bytes + padding)."""
    jpeg_bytes = b"\xff\xd8\xff" + b"\x00" * 10
    return base64.b64encode(jpeg_bytes).decode()


def _make_jpeg_bytes() -> bytes:
    return b"\xff\xd8\xff" + b"\x00" * 10


def _make_png_b64() -> str:
    """Minimal valid PNG header."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    return base64.b64encode(png_bytes).decode()


MOCK_EMBEDDING = [0.1] * 1536  # must match EMBEDDING_DIMENSIONS in embedding.py
MOCK_SEARCH_RESULTS = [
    {"image_id": "site-photo-01.jpg", "similarity_score": 0.95},
    {"image_id": "site-photo-02.jpg", "similarity_score": 0.88},
]
MOCK_ENRICHED = [
    {
        "image_id": "site-photo-01.jpg",
        "filename": "site-photo-01.jpg",
        "project_id": "PROJ-001",
        "project_name": "Harbor Bridge Reconstruction",
        "date_taken": "2024-04-15T08:30:00-07:00",
        "taken_by": "John Smith",
        "location": "Pier P-3, East Side",
        "tags": [],
        "ai_description": None,
        "ai_labels": [],
        "similarity_score": 0.95,
    },
    {
        "image_id": "site-photo-02.jpg",
        "filename": "site-photo-02.jpg",
        "project_id": "PROJ-001",
        "project_name": "Harbor Bridge Reconstruction",
        "date_taken": "2024-04-20T14:15:00-07:00",
        "taken_by": "John Smith",
        "location": "Station 4+50, Deck Level",
        "tags": [],
        "ai_description": None,
        "ai_labels": [],
        "similarity_score": 0.88,
    },
]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_success_jpeg(mock_embed, mock_search, mock_enrich):
    resp = client.post(
        "/search/similar",
        json={"image": _make_jpeg_b64(), "top_k": 2},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "query_time_ms" in body
    assert len(body["results"]) == 2
    assert body["results"][0]["similarity_score"] == 0.95


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_success_png(mock_embed, mock_search, mock_enrich):
    resp = client.post(
        "/search/similar",
        json={"image": _make_png_b64(), "top_k": 2},
    )
    assert resp.status_code == 200
    assert len(resp.json()["results"]) == 2


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_success_with_project_filter(mock_embed, mock_search, mock_enrich):
    resp = client.post(
        "/search/similar",
        json={"image": _make_png_b64(), "top_k": 5, "project_id": "PROJ-001"},
    )
    assert resp.status_code == 200
    _, kwargs = mock_search.call_args
    assert kwargs["project_id"] == "PROJ-001"


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=[])
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=[])
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_empty_results(mock_embed, mock_search, mock_enrich):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_response_contains_query_time_ms(mock_embed, mock_search, mock_enrich):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 200
    assert isinstance(resp.json()["query_time_ms"], int)
    assert resp.json()["query_time_ms"] >= 0


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_default_top_k_is_10(mock_embed, mock_search, mock_enrich):
    """When top_k is omitted the default of 10 must be forwarded to the search core."""
    client.post("/search/similar", json={"image": _make_jpeg_b64()})
    _, kwargs = mock_search.call_args
    assert kwargs["top_k"] == 10


# ---------------------------------------------------------------------------
# Call-chain verification — embed → search → enrich wiring
# ---------------------------------------------------------------------------

@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_embed_image_called_with_decoded_bytes(mock_embed, mock_search, mock_enrich):
    """embed_image must receive the decoded bytes, not the base64 string."""
    jpeg_b64 = _make_jpeg_b64()
    expected_bytes = base64.b64decode(jpeg_b64)

    client.post("/search/similar", json={"image": jpeg_b64})

    mock_embed.assert_called_once()
    actual_bytes = mock_embed.call_args[0][0]
    assert actual_bytes == expected_bytes


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_run_similarity_search_receives_embedding_from_embed_image(mock_embed, mock_search, mock_enrich):
    """The vector returned by embed_image must be forwarded to run_similarity_search."""
    custom_embedding = [0.42] * 1024
    mock_embed.return_value = custom_embedding

    client.post("/search/similar", json={"image": _make_jpeg_b64()})

    _, kwargs = mock_search.call_args
    assert kwargs["embedding"] == custom_embedding


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_enrich_results_receives_raw_search_output(mock_embed, mock_search, mock_enrich):
    """enrich_results must receive exactly what run_similarity_search returned."""
    custom_results = [{"image_id": "x.jpg", "similarity_score": 0.77}]
    mock_search.return_value = custom_results

    client.post("/search/similar", json={"image": _make_jpeg_b64()})

    enrich_call_args = mock_enrich.call_args[0][0]
    assert enrich_call_args == custom_results


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_call_order_embed_then_search_then_enrich(mock_embed, mock_search, mock_enrich):
    """The three async calls must happen in order: embed → search → enrich."""
    manager = MagicMock()
    manager.attach_mock(mock_embed,  "embed")
    manager.attach_mock(mock_search, "search")
    manager.attach_mock(mock_enrich, "enrich")

    client.post("/search/similar", json={"image": _make_jpeg_b64()})

    call_names = [c[0] for c in manager.mock_calls]
    assert call_names.index("embed") < call_names.index("search")
    assert call_names.index("search") < call_names.index("enrich")


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_request_id_forwarded_to_search_core(mock_embed, mock_search, mock_enrich):
    """A request_id must be forwarded to run_similarity_search for tracing."""
    client.post("/search/similar", json={"image": _make_jpeg_b64()})
    _, kwargs = mock_search.call_args
    assert "request_id" in kwargs
    assert kwargs["request_id"]  # non-empty


@patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=MOCK_ENRICHED)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_no_project_filter_passes_none_to_search_core(mock_embed, mock_search, mock_enrich):
    """When project_id is omitted, None must be forwarded to run_similarity_search."""
    client.post("/search/similar", json={"image": _make_jpeg_b64()})
    _, kwargs = mock_search.call_args
    assert kwargs["project_id"] is None


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_missing_image_field():
    resp = client.post("/search/similar", json={"top_k": 5})
    assert resp.status_code == 400
    assert resp.json()["code"] == "MISSING_FIELD"


def test_invalid_base64():
    resp = client.post("/search/similar", json={"image": "not-valid-base64!!!"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_BASE64"


def test_unsupported_image_format():
    bad_image = base64.b64encode(b"\x00\x01\x02\x03" * 10).decode()
    resp = client.post("/search/similar", json={"image": bad_image})
    assert resp.status_code == 400
    assert resp.json()["code"] == "UNSUPPORTED_FORMAT"


def test_image_too_large():
    big = b"\xff\xd8\xff" + b"\x00" * (6 * 1024 * 1024)
    resp = client.post("/search/similar", json={"image": base64.b64encode(big).decode()})
    assert resp.status_code == 400
    assert resp.json()["code"] == "IMAGE_TOO_LARGE"


def test_invalid_top_k_too_high():
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64(), "top_k": 99})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_TOP_K"


def test_invalid_top_k_zero():
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64(), "top_k": 0})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_TOP_K"


def test_invalid_project_id_empty():
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64(), "project_id": ""})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_PROJECT_ID"


def test_top_k_boundary_1_accepted():
    """top_k=1 is the minimum valid value."""
    with (
        patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING),
        patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=[]),
        patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=[]),
    ):
        resp = client.post("/search/similar", json={"image": _make_jpeg_b64(), "top_k": 1})
    assert resp.status_code == 200


def test_top_k_boundary_50_accepted():
    """top_k=50 is the maximum valid value."""
    with (
        patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING),
        patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=[]),
        patch("app.routes.search.enrich_results", new_callable=AsyncMock, return_value=[]),
    ):
        resp = client.post("/search/similar", json={"image": _make_jpeg_b64(), "top_k": 50})
    assert resp.status_code == 200


def test_top_k_boundary_51_rejected():
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64(), "top_k": 51})
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_TOP_K"


# ---------------------------------------------------------------------------
# Upstream errors
# ---------------------------------------------------------------------------

@patch(
    "app.routes.search.embed_image",
    new_callable=AsyncMock,
    side_effect=__import__(
        "app.services.embedding", fromlist=["EmbeddingError"]
    ).EmbeddingError("EMBEDDING_TIMEOUT", "Timed out"),
)
def test_embedding_timeout(mock_embed):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 504
    assert resp.json()["code"] == "EMBEDDING_TIMEOUT"


@patch(
    "app.routes.search.embed_image",
    new_callable=AsyncMock,
    side_effect=__import__(
        "app.services.embedding", fromlist=["EmbeddingError"]
    ).EmbeddingError("EMBEDDING_FAILED", "Bedrock error"),
)
def test_embedding_failed_returns_502(mock_embed):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 502
    assert resp.json()["code"] == "EMBEDDING_FAILED"


@patch(
    "app.routes.search.run_similarity_search",
    new_callable=AsyncMock,
    side_effect=__import__(
        "app.services.search_core", fromlist=["SearchCoreError"]
    ).SearchCoreError("boom"),
)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_search_core_error(mock_embed, mock_search):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 502
    assert resp.json()["code"] == "SEARCH_FAILED"


@patch(
    "app.routes.search.enrich_results",
    new_callable=AsyncMock,
    side_effect=Exception("OpenSearch down"),
)
@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock, return_value=MOCK_SEARCH_RESULTS)
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_enrich_failure_returns_502(mock_embed, mock_search, mock_enrich):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 502
    assert resp.json()["code"] == "SEARCH_FAILED"


@patch("app.routes.search.embed_image", new_callable=AsyncMock)
def test_search_core_not_called_when_embed_fails(mock_embed):
    """If embed_image raises, run_similarity_search must not be called."""
    from app.services.embedding import EmbeddingError
    mock_embed.side_effect = EmbeddingError("EMBEDDING_FAILED", "fail")

    with patch(
        "app.routes.search.run_similarity_search", new_callable=AsyncMock
    ) as mock_search:
        client.post("/search/similar", json={"image": _make_jpeg_b64()})
        mock_search.assert_not_called()


# ---------------------------------------------------------------------------
# Search core unit tests (search_core.py in isolation)
# ---------------------------------------------------------------------------

class TestSearchCore:
    """
    Tests for run_similarity_search() that verify it correctly delegates
    to VectorStore.search_by_embedding() and normalises the response.
    """

    def _make_mock_vs(self, results: list[dict]) -> MagicMock:
        mock_vs = MagicMock()
        mock_vs.search_by_embedding.return_value = results
        return mock_vs

    @pytest.mark.asyncio
    async def test_delegates_to_vector_store(self):
        from app.services.search_core import run_similarity_search
        import app.services.search_core as sc

        mock_vs = self._make_mock_vs([
            {"image_id": "a.jpg", "score": 0.9},
            {"image_id": "b.jpg", "score": 0.7},
        ])
        sc._vector_store = mock_vs

        results = await run_similarity_search([0.1] * 1536, top_k=5, project_id=None, request_id="r1")

        mock_vs.search_by_embedding.assert_called_once()
        assert len(results) == 2

        sc._vector_store = None  # reset singleton

    @pytest.mark.asyncio
    async def test_score_field_renamed_to_similarity_score(self):
        from app.services.search_core import run_similarity_search
        import app.services.search_core as sc

        mock_vs = self._make_mock_vs([{"image_id": "a.jpg", "score": 0.85}])
        sc._vector_store = mock_vs

        results = await run_similarity_search([0.1] * 1536, top_k=1, project_id=None, request_id="r1")

        assert "similarity_score" in results[0]
        assert "score" not in results[0]
        assert results[0]["similarity_score"] == 0.85

        sc._vector_store = None

    @pytest.mark.asyncio
    async def test_project_filter_passed_as_search_filters_instance(self):
        from app.services.search_core import run_similarity_search
        import app.services.search_core as sc

        mock_vs = self._make_mock_vs([])
        sc._vector_store = mock_vs

        await run_similarity_search([0.1] * 1536, top_k=5, project_id="PROJ-001", request_id="r1")

        call_kwargs = mock_vs.search_by_embedding.call_args[1]
        filters = call_kwargs["filters"]
        # Must be a SearchFilters instance, not a raw dict
        assert hasattr(filters, "project_id"), "filters must be a SearchFilters instance"
        assert filters.project_id == "PROJ-001"

        sc._vector_store = None

    @pytest.mark.asyncio
    async def test_no_project_filter_passes_none(self):
        from app.services.search_core import run_similarity_search
        import app.services.search_core as sc

        mock_vs = self._make_mock_vs([])
        sc._vector_store = mock_vs

        await run_similarity_search([0.1] * 1536, top_k=5, project_id=None, request_id="r1")

        call_kwargs = mock_vs.search_by_embedding.call_args[1]
        assert call_kwargs["filters"] is None

        sc._vector_store = None

    @pytest.mark.asyncio
    async def test_vector_store_exception_raises_search_core_error(self):
        from app.services.search_core import run_similarity_search, SearchCoreError
        import app.services.search_core as sc

        mock_vs = MagicMock()
        mock_vs.search_by_embedding.side_effect = Exception("OpenSearch down")
        sc._vector_store = mock_vs

        with pytest.raises(SearchCoreError):
            await run_similarity_search([0.1] * 1536, top_k=5, project_id=None, request_id="r1")

        sc._vector_store = None

    @pytest.mark.asyncio
    async def test_scores_rounded_to_4_decimal_places(self):
        from app.services.search_core import run_similarity_search
        import app.services.search_core as sc

        mock_vs = self._make_mock_vs([{"image_id": "a.jpg", "score": 0.123456789}])
        sc._vector_store = mock_vs

        results = await run_similarity_search([0.1] * 1536, top_k=1, project_id=None, request_id="r1")

        assert results[0]["similarity_score"] == 0.1235

        sc._vector_store = None
