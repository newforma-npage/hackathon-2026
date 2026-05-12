"""
handler.py — Lambda entry point for the POST /events endpoint.

Accepts an API Gateway proxy event, validates the JWT authorizer context,
parses the KPI event payload, and emits the corresponding CloudWatch metric.

Supported event types:
- ``ImageReuse`` — user selects an image for use in another project
- ``FirstResultRelevance`` — user marks a search result as relevant on first attempt

Environment variables
---------------------
CLOUDWATCH_NAMESPACE
    CloudWatch namespace for all KPI metrics.
    Defaults to ``VisualProjectIntelligenceSearch``.
AWS_REGION
    AWS region for the CloudWatch client.  Defaults to ``us-east-1``.

Requirements: 10.1, 10.2, 10.3, 10.4
"""

from __future__ import annotations

import json
import logging
from typing import Any

from events_handler.metrics import emit_first_result_relevance, emit_image_reuse

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Supported event types and their required fields
# ---------------------------------------------------------------------------

_EVENT_REQUIRED_FIELDS: dict[str, list[str]] = {
    "ImageReuse": ["image_id", "destination_project_id"],
    "FirstResultRelevance": ["query", "image_id"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Build an API Gateway proxy-compatible response dict."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point for ``POST /events``.

    Parameters
    ----------
    event:
        API Gateway proxy event dict.
    context:
        Lambda context object (unused).

    Returns
    -------
    dict
        API Gateway proxy response with ``statusCode``, ``headers``, and
        ``body`` (JSON string).

    Response codes
    --------------
    200
        Event accepted and metric emitted.
    400
        Invalid or missing ``event_type``, or missing required fields.
    401
        Authorizer context is missing or has no ``claims``.
    """

    # ------------------------------------------------------------------
    # 1. Auth guard — verify Cognito Authorizer context
    # ------------------------------------------------------------------
    request_context: dict[str, Any] = event.get("requestContext") or {}
    authorizer: dict[str, Any] | None = request_context.get("authorizer")
    if not authorizer or not authorizer.get("claims"):
        logger.warning("Request rejected: missing or empty authorizer context")
        return _make_response(401, {"error": "Unauthorized"})

    # ------------------------------------------------------------------
    # 2. Parse request body
    # ------------------------------------------------------------------
    raw_body: str | None = event.get("body")
    try:
        body: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except (json.JSONDecodeError, TypeError):
        return _make_response(
            400, {"error": "INVALID_BODY", "message": "Request body must be valid JSON"}
        )

    # ------------------------------------------------------------------
    # 3. Validate event_type
    # ------------------------------------------------------------------
    event_type: str | None = body.get("event_type")

    if not event_type:
        return _make_response(
            400,
            {"error": "MISSING_EVENT_TYPE", "message": "event_type is required"},
        )

    if event_type not in _EVENT_REQUIRED_FIELDS:
        return _make_response(
            400,
            {
                "error": "UNKNOWN_EVENT_TYPE",
                "message": f"Unsupported event_type: {event_type}. "
                f"Supported types: {list(_EVENT_REQUIRED_FIELDS.keys())}",
            },
        )

    # ------------------------------------------------------------------
    # 4. Validate required fields for the event type
    # ------------------------------------------------------------------
    required_fields = _EVENT_REQUIRED_FIELDS[event_type]
    missing_fields = [f for f in required_fields if not body.get(f)]

    if missing_fields:
        return _make_response(
            400,
            {
                "error": "MISSING_FIELDS",
                "message": f"Missing required fields for {event_type}: {missing_fields}",
            },
        )

    # ------------------------------------------------------------------
    # 5. Emit the appropriate metric
    # ------------------------------------------------------------------
    if event_type == "ImageReuse":
        emit_image_reuse(
            image_id=body["image_id"],
            destination_project_id=body["destination_project_id"],
        )
    elif event_type == "FirstResultRelevance":
        emit_first_result_relevance(
            query=body["query"],
            image_id=body["image_id"],
        )

    logger.info("KPI event processed: %s", event_type)

    return _make_response(
        200,
        {"message": f"{event_type} event recorded successfully"},
    )
