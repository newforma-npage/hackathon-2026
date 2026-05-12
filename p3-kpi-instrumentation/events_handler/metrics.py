"""
metrics.py — CloudWatch metric emission utilities for KPI events.

Provides helper functions to emit ``ImageReuseEvent`` and
``FirstResultRelevance`` metrics to CloudWatch under the
``VisualProjectIntelligenceSearch`` namespace.

Failures are logged but never propagated — metric emission must not
affect the API response.

Requirements: 10.2, 10.3, 10.4
"""

from __future__ import annotations

import logging
import os

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CW_NAMESPACE: str = os.environ.get(
    "CLOUDWATCH_NAMESPACE", "VisualProjectIntelligenceSearch"
)


def _get_cloudwatch_client():
    """Return a CloudWatch client for the configured region."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.client("cloudwatch", region_name=region)


def emit_image_reuse(image_id: str, destination_project_id: str) -> None:
    """Emit an ``ImageReuseEvent`` metric to CloudWatch.

    Parameters
    ----------
    image_id:
        The ID of the image being reused.
    destination_project_id:
        The project the image is being reused in.
    """
    try:
        cw = _get_cloudwatch_client()
        cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "ImageReuseEvent",
                    "Dimensions": [
                        {"Name": "image_id", "Value": image_id},
                        {"Name": "destination_project_id", "Value": destination_project_id},
                    ],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
        logger.info(
            "Emitted ImageReuseEvent: image_id=%s, destination_project_id=%s",
            image_id,
            destination_project_id,
        )
    except Exception as exc:
        logger.warning("Failed to emit ImageReuseEvent metric: %s", exc)


def emit_first_result_relevance(query: str, image_id: str) -> None:
    """Emit a ``FirstResultRelevance`` metric to CloudWatch.

    Parameters
    ----------
    query:
        The search query that produced the relevant result.
    image_id:
        The ID of the image marked as relevant.
    """
    try:
        cw = _get_cloudwatch_client()
        cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "FirstResultRelevance",
                    "Dimensions": [
                        {"Name": "query", "Value": query[:256]},
                        {"Name": "image_id", "Value": image_id},
                    ],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
        logger.info(
            "Emitted FirstResultRelevance: query=%s, image_id=%s",
            query,
            image_id,
        )
    except Exception as exc:
        logger.warning("Failed to emit FirstResultRelevance metric: %s", exc)
