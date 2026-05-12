"""
Unit tests for POST /search/similar.

Run with:  pytest tests/ -v

These tests mock out Bedrock and the search core so no AWS credentials are needed.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, patch

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


def _make_png_b64() -> str:
    """Minimal valid PNG header."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
    return base64.b64encode(png_bytes).decode()


MOCK_EMBEDDING = [0.1] * 1024
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
    # Valid base64 but not JPEG/PNG
    bad_image = base64.b64encode(b"\x00\x01\x02\x03" * 10).decode()
    resp = client.post("/search/similar", json={"image": bad_image})
    assert resp.status_code == 400
    assert resp.json()["code"] == "UNSUPPORTED_FORMAT"


def test_image_too_large():
    # 6 MB of JPEG-magic-prefixed zeros
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


# ---------------------------------------------------------------------------
# Upstream errors
# ---------------------------------------------------------------------------

@patch("app.routes.search.embed_image", new_callable=AsyncMock,
       side_effect=__import__("app.services.embedding", fromlist=["EmbeddingError"]).EmbeddingError(
           "EMBEDDING_TIMEOUT", "Timed out"))
def test_embedding_timeout(mock_embed):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 504
    assert resp.json()["code"] == "EMBEDDING_TIMEOUT"


@patch("app.routes.search.run_similarity_search", new_callable=AsyncMock,
       side_effect=__import__("app.services.search_core", fromlist=["SearchCoreError"]).SearchCoreError("boom"))
@patch("app.routes.search.embed_image", new_callable=AsyncMock, return_value=MOCK_EMBEDDING)
def test_search_core_error(mock_embed, mock_search):
    resp = client.post("/search/similar", json={"image": _make_jpeg_b64()})
    assert resp.status_code == 502
    assert resp.json()["code"] == "SEARCH_FAILED"
