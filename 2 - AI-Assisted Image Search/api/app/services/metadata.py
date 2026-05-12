"""
Metadata enrichment — fetches image metadata from OpenSearch by image_id
and merges it into the raw search results.

The OpenSearch index is populated by P1 (ingest) and P2 (tag enrichment).
Each document is stored with _id == filename (e.g. "site-photo-03.jpg").
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import boto3
from opensearchpy import AsyncOpenSearch, RequestsAWSV4SignerAuth

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — read from environment variables
# ---------------------------------------------------------------------------

OPENSEARCH_HOST = os.environ.get("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.environ.get("OPENSEARCH_PORT", "9200"))
# Match the index name used by the ingestion backend (vector_store.py default)
OPENSEARCH_INDEX = os.environ.get("OPENSEARCH_INDEX", os.environ.get("VECTOR_INDEX_NAME", "visual-project-intelligence"))
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Fields to return from OpenSearch (avoids fetching the large embedding vector)
_SOURCE_FIELDS = [
    "filename",
    "project_id",
    "project_name",
    "date_taken",
    "taken_by",
    "location",
    "tags",
    "ai_description",
    "ai_labels",
]


def _get_client() -> AsyncOpenSearch:
    """Build an AsyncOpenSearch client with AWS SigV4 auth."""
    credentials = boto3.Session().get_credentials()
    auth = RequestsAWSV4SignerAuth(credentials, AWS_REGION, "es")
    return AsyncOpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=None,  # uses default aiohttp transport
    )


async def enrich_results(
    raw_results: List[Dict[str, Any]],
    request_id: str,
) -> List[Dict[str, Any]]:
    """
    Fetch metadata for each image_id in *raw_results* and return enriched dicts.

    Results whose image_id is not found in the index are dropped (with a WARNING).
    The returned list preserves the original similarity_score ordering.
    """
    if not raw_results:
        return []

    client = _get_client()

    try:
        image_ids = [r["image_id"] for r in raw_results]

        # Bulk fetch via mget — one round-trip for all IDs
        response = await client.mget(
            body={"ids": image_ids},
            index=OPENSEARCH_INDEX,
            _source_includes=_SOURCE_FIELDS,
        )

        # Build a lookup: image_id → metadata dict
        metadata_by_id: Dict[str, Optional[Dict[str, Any]]] = {}
        for doc in response["docs"]:
            if doc.get("found"):
                metadata_by_id[doc["_id"]] = doc.get("_source", {})
            else:
                metadata_by_id[doc["_id"]] = None

        enriched: List[Dict[str, Any]] = []
        for raw in raw_results:
            iid = raw["image_id"]
            meta = metadata_by_id.get(iid)

            if meta is None:
                logger.warning(
                    "image_id '%s' not found in OpenSearch index '%s'",
                    iid,
                    OPENSEARCH_INDEX,
                    extra={"request_id": request_id},
                )
                continue  # drop missing images per Req 4.5

            enriched.append(
                {
                    "image_id": iid,
                    "filename": meta.get("filename"),
                    "project_id": meta.get("project_id"),
                    "project_name": meta.get("project_name"),
                    "date_taken": meta.get("date_taken"),
                    "taken_by": meta.get("taken_by"),
                    "location": meta.get("location"),
                    "tags": meta.get("tags"),
                    "ai_description": meta.get("ai_description"),
                    "ai_labels": meta.get("ai_labels"),
                    "similarity_score": raw["similarity_score"],
                }
            )

        return enriched

    finally:
        await client.close()
