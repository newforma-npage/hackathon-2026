"""
test_events_handler.py — Unit tests for the POST /events KPI Lambda handler.

Tests cover:
- Valid ImageReuse event → 200, metric emitted
- Valid FirstResultRelevance event → 200, metric emitted
- Missing event_type → 400
- Unknown event_type → 400
- Missing required fields → 400
- Missing auth → 401

Requirements: 10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from events_handler.handler import handler


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_event(body: dict | None = None, authenticated: bool = True) -> dict:
    """Build a minimal API Gateway proxy event for testing."""
    event: dict = {
        "httpMethod": "POST",
        "path": "/events",
        "headers": {"Content-Type": "application/json"},
        "requestContext": {},
        "body": json.dumps(body) if body is not None else None,
    }
    if authenticated:
        event["requestContext"]["authorizer"] = {
            "claims": {
                "sub": "user-123",
                "email": "test@example.com",
            }
        }
    return event


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuthGuard:
    """Verify that unauthenticated requests are rejected."""

    def test_missing_auth_returns_401(self):
        event = _make_event(body={"event_type": "ImageReuse"}, authenticated=False)
        response = handler(event, None)

        assert response["statusCode"] == 401
        body = json.loads(response["body"])
        assert body["error"] == "Unauthorized"

    def test_empty_authorizer_returns_401(self):
        event = _make_event(body={"event_type": "ImageReuse"}, authenticated=False)
        event["requestContext"]["authorizer"] = {}
        response = handler(event, None)

        assert response["statusCode"] == 401


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestValidation:
    """Verify request body validation."""

    def test_missing_event_type_returns_400(self):
        event = _make_event(body={"image_id": "img-1"})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_EVENT_TYPE"

    def test_unknown_event_type_returns_400(self):
        event = _make_event(body={"event_type": "UnknownEvent"})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "UNKNOWN_EVENT_TYPE"
        assert "UnknownEvent" in body["message"]

    def test_image_reuse_missing_fields_returns_400(self):
        event = _make_event(body={"event_type": "ImageReuse", "image_id": "img-1"})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_FIELDS"
        assert "destination_project_id" in body["message"]

    def test_first_result_relevance_missing_fields_returns_400(self):
        event = _make_event(body={"event_type": "FirstResultRelevance", "query": "cracks"})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_FIELDS"
        assert "image_id" in body["message"]

    def test_empty_body_returns_400(self):
        event = _make_event(body={})
        response = handler(event, None)

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert body["error"] == "MISSING_EVENT_TYPE"


# ---------------------------------------------------------------------------
# Success tests
# ---------------------------------------------------------------------------


class TestImageReuseEvent:
    """Verify successful ImageReuse event processing."""

    @patch("events_handler.handler.emit_image_reuse")
    def test_valid_image_reuse_returns_200(self, mock_emit):
        event = _make_event(
            body={
                "event_type": "ImageReuse",
                "image_id": "img-abc-123",
                "destination_project_id": "PROJ-002",
            }
        )
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "ImageReuse" in body["message"]

        mock_emit.assert_called_once_with(
            image_id="img-abc-123",
            destination_project_id="PROJ-002",
        )


class TestFirstResultRelevanceEvent:
    """Verify successful FirstResultRelevance event processing."""

    @patch("events_handler.handler.emit_first_result_relevance")
    def test_valid_first_result_relevance_returns_200(self, mock_emit):
        event = _make_event(
            body={
                "event_type": "FirstResultRelevance",
                "query": "foundation cracks",
                "image_id": "img-xyz-789",
            }
        )
        response = handler(event, None)

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert "FirstResultRelevance" in body["message"]

        mock_emit.assert_called_once_with(
            query="foundation cracks",
            image_id="img-xyz-789",
        )
