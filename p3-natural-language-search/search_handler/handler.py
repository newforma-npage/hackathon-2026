"""
handler.py — Lambda entry point for the POST /search endpoint.

Accepts an API Gateway proxy event, validates the JWT authorizer context,
embeds the query text via Bedrock Titan, executes an ANN kNN search against
the ``image-embeddings`` OpenSearch Serverless index, and returns ranked
results.

Environment variables
---------------------
OPENSEARCH_ENDPOINT
    Hostname (without scheme) of the OpenSearch Serverless collection endpoint,
    e.g. ``abc123.us-east-1.aoss.amazonaws.com``.
AWS_REGION
    AWS region used for both Bedrock and OpenSearch clients.  Defaults to
    ``us-east-1`` if not set.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 10.1, 10.4
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

from search_handler.bedrock import BedrockUnavailableError, embed_query_text
from search_handler.opensearch_client import OpenSearchUnavailableError, run_ann_search
from search_handler.query_builder import build_knn_query

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# CloudWatch namespace / metric constants
# ---------------------------------------------------------------------------

_CW_NAMESPACE: str = "VisualProjectIntelligenceSearch"
_CW_METRIC_LATENCY: str = "SearchLatencyMs"

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


def _build_os_client() -> OpenSearch:
    """Create an ``opensearch-py`` client authenticated with SigV4.

    Reads ``OPENSEARCH_ENDPOINT`` and ``AWS_REGION`` from the environment.
    """
    endpoint: str = os.environ["OPENSEARCH_ENDPOINT"]
    region: str = os.environ.get("AWS_REGION", "us-east-1")

    credentials = boto3.Session().get_credentials()
    awsauth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        region,
        "aoss",
        session_token=credentials.token,
    )

    return OpenSearch(
        hosts=[{"host": endpoint, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
    )


def _put_latency_metric(
    latency_ms: float,
    project_id: str | None,
) -> None:
    """Publish ``SearchLatencyMs`` to CloudWatch.

    Failures are logged but never propagated — metric emission must not
    affect the search response.
    """
    try:
        cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        dimensions = [{"Name": "project_id", "Value": project_id or "unknown"}]
        cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": _CW_METRIC_LATENCY,
                    "Dimensions": dimensions,
                    "Value": latency_ms,
                    "Unit": "Milliseconds",
                }
            ],
        )
        logger.debug(
            "Published %s=%.1f ms to CloudWatch (project_id=%s)",
            _CW_METRIC_LATENCY,
            latency_ms,
            project_id,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to publish CloudWatch metric: %s", exc)


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """AWS Lambda entry point for ``POST /search``.

    Parameters
    ----------
    event:
        API Gateway proxy event dict.
    context:
        Lambda context object (unused beyond logging).

    Returns
    -------
    dict
        API Gateway proxy response with ``statusCode``, ``headers``, and
        ``body`` (JSON string).

    Response codes
    --------------
    200
        Search succeeded.  Body: ``{"results": [...], "count": N, "message": null}``
        or ``{"results": [], "count": 0, "message": "No images matched your query"}``
        when the index returns zero hits.
    400
        ``query`` field is absent or empty.
        Body: ``{"error": "EMPTY_QUERY", "message": "query is required"}``
    401
        Authorizer context is missing or has no ``claims``.
        Body: ``{"error": "Unauthorized"}``
    503
        Bedrock or OpenSearch is unavailable.
        Body: ``{"error": "Search service temporarily unavailable"}``
    """
    start_time: float = time.monotonic()
    project_id: str | None = None

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
        body = {}

    query_text: str = body.get("query", "") or ""
    k: int = int(body.get("k", 20))
    filters: dict[str, Any] = body.get("filters") or {}

    # Derive project_id for CloudWatch dimension (best-effort)
    project_id = filters.get("project_id") or authorizer.get("claims", {}).get("custom:projectId")

    # ------------------------------------------------------------------
    # 3. Validate query
    # ------------------------------------------------------------------
    if not query_text.strip():
        logger.info("Request rejected: empty query")
        return _make_response(
            400,
            {"error": "EMPTY_QUERY", "message": "query is required"},
        )

    # ------------------------------------------------------------------
    # 4. Execute search pipeline
    # ------------------------------------------------------------------
    try:
        # 4a. Embed query text via Bedrock
        logger.info("Embedding query text (length=%d)", len(query_text))
        query_vector: list[float] = embed_query_text(query_text)

        # 4b. Build kNN query with filters
        knn_query: dict[str, Any] = build_knn_query(query_vector, k=k, filters=filters)

        # 4c. Execute ANN search against OpenSearch
        os_client = _build_os_client()
        results: list[dict[str, Any]] = run_ann_search(knn_query, os_client)

    except (BedrockUnavailableError, OpenSearchUnavailableError) as exc:
        logger.error("Search service unavailable: %s", exc)
        elapsed_ms = (time.monotonic() - start_time) * 1000
        _put_latency_metric(elapsed_ms, project_id)
        return _make_response(
            503,
            {"error": "Search service temporarily unavailable"},
        )

    # ------------------------------------------------------------------
    # 5. Publish latency metric
    # ------------------------------------------------------------------
    elapsed_ms = (time.monotonic() - start_time) * 1000
    logger.info("Search completed in %.1f ms, %d result(s)", elapsed_ms, len(results))
    _put_latency_metric(elapsed_ms, project_id)

    # ------------------------------------------------------------------
    # 6. Build response
    # ------------------------------------------------------------------
    if not results:
        return _make_response(
            200,
            {
                "results": [],
                "count": 0,
                "message": "No images matched your query",
            },
        )

    return _make_response(
        200,
        {
            "results": results,
            "count": len(results),
            "message": None,
        },
    )
