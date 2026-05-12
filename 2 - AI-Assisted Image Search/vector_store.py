"""
VectorStore client module for OpenSearch Serverless.

Wraps the opensearchpy client with SigV4 authentication and exposes
index_image, search_by_embedding, and delete_image for use by downstream
consumers (Dev 3 — Bedrock embeddings, Dev 5 — Search API).

Tag normalisation
-----------------
All tags are normalised before being stored in the index.  The canonical
normalisation logic lives in p2-rekognition-labelling/tagging_handler/normaliser.py
and is reproduced here as a pure function so this module remains independently
deployable without a cross-directory import dependency.

Normalisation steps (applied in order):
  1. Extract the ``Name`` field if the input is a Rekognition label dict.
  2. Lowercase.
  3. Deduplicate (case-insensitive, preserving first-seen order).
  4. Strip non-alphanumeric characters except hyphens and spaces.
  5. Strip leading/trailing whitespace.
  6. Discard empty strings.
"""

import logging
import os
import re

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import NotFoundError, OpenSearchException

logger = logging.getLogger(__name__)

_EMBEDDING_DIM = 1536
_INDEX_NAME = "images"
_AWS_REGION = "us-east-1"
_AOSS_SERVICE = "aoss"


# ---------------------------------------------------------------------------
# Tag normalisation
# Canonical source: p2-rekognition-labelling/tagging_handler/normaliser.py
# ---------------------------------------------------------------------------

def normalise_tags(labels: list) -> list[str]:
    """
    Normalise a list of raw Rekognition labels (or plain strings) into
    canonical, unique, lowercase tag strings.

    Accepts either plain strings or Rekognition label dicts (``{"Name": ...}``).

    Steps:
      1. Extract ``Name`` from dicts.
      2. Lowercase.
      3. Deduplicate (case-insensitive, first-seen order preserved).
      4. Strip non-alphanumeric characters except hyphens and spaces.
      5. Strip leading/trailing whitespace.
      6. Discard empty strings.

    Examples:
        >>> normalise_tags(["Bridge", "bridge", "Concrete Crack"])
        ['bridge', 'concrete crack']
        >>> normalise_tags([{"Name": "Steel Beam"}, "steel beam"])
        ['steel beam']
    """
    seen: set[str] = set()
    result: list[str] = []

    for raw in labels:
        text: str = raw.get("Name", "") if isinstance(raw, dict) else str(raw)
        text = text.lower()
        if text in seen:
            continue
        seen.add(text)
        text = re.sub(r"[^a-z0-9\- ]", "", text)
        text = text.strip()
        if text:
            result.append(text)

    return result


class VectorStore:
    def __init__(self, endpoint: str | None = None):
        """
        Initialise the VectorStore client.

        Parameters
        ----------
        endpoint : str, optional
            OpenSearch Serverless collection endpoint URL.
            Falls back to the OPENSEARCH_ENDPOINT environment variable.

        Raises
        ------
        ValueError
            If no endpoint is provided and OPENSEARCH_ENDPOINT is not set.
        """
        resolved_endpoint = endpoint or os.environ.get("OPENSEARCH_ENDPOINT")
        if not resolved_endpoint:
            raise ValueError(
                "OpenSearch endpoint must be provided either as the 'endpoint' "
                "constructor argument or via the OPENSEARCH_ENDPOINT environment variable."
            )

        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, _AWS_REGION, _AOSS_SERVICE)

        # Strip trailing slash and scheme for the host parameter
        host = resolved_endpoint.rstrip("/")
        if host.startswith("https://"):
            host = host[len("https://"):]
        elif host.startswith("http://"):
            host = host[len("http://"):]

        self._client = OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )

    def index_image(
        self,
        image_id: str,
        project_id: str,
        embedding: list[float],
        tags: list[str],
        date: str,
        location: str,
    ) -> dict:
        """
        Index a single image document.

        Parameters
        ----------
        image_id : str
            Unique identifier for the image; used as the OpenSearch document _id.
        project_id : str
            Project the image belongs to.
        embedding : list[float]
            1536-dimensional float32 vector from Bedrock Titan Multimodal.
        tags : list[str | dict]
            AI-generated or manual tags (e.g. ["bridge", "concrete crack"]).
            Accepts plain strings or Rekognition label dicts (``{"Name": ...}``).
            Tags are normalised (lowercase, deduplicated, stripped) before storage.
        date : str
            ISO 8601 date string (e.g. "2024-04-15T08:30:00-07:00").
        location : str
            Human-readable location string (e.g. "Pier P-3, East Side").

        Returns
        -------
        dict
            The OpenSearch index API response.

        Raises
        ------
        ValueError
            If embedding does not have exactly 1536 dimensions.
        opensearchpy.OpenSearchException
            Re-raised after logging if the API call fails.
        """
        if len(embedding) != _EMBEDDING_DIM:
            raise ValueError(
                f"embedding must have exactly {_EMBEDDING_DIM} dimensions, "
                f"got {len(embedding)}."
            )

        normalised_tags = normalise_tags(tags)

        body = {
            "image_id": image_id,
            "project_id": project_id,
            "embedding": embedding,
            "tags": normalised_tags,
            "date": date,
            "location": location,
        }

        try:
            return self._client.index(index=_INDEX_NAME, id=image_id, body=body)
        except OpenSearchException as exc:
            logger.error("index_image failed: %s", exc)
            raise

    def search_by_embedding(
        self,
        embedding_vector: list[float],
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Search for images by vector similarity.

        Parameters
        ----------
        embedding_vector : list[float]
            1536-dimensional query embedding.
        top_k : int, optional
            Maximum number of results to return (default 10).
        filters : dict, optional
            OpenSearch bool filter clause dict, e.g.:
            {"term": {"project_id": "PROJ-001"}}
            or {"range": {"date": {"gte": "2024-01-01"}}}

        Returns
        -------
        list[dict]
            List of result dicts, each containing:
            image_id, project_id, tags, date, location, score.

        Raises
        ------
        ValueError
            If embedding_vector does not have exactly 1536 dimensions.
        opensearchpy.OpenSearchException
            Re-raised after logging if the API call fails.
        """
        if len(embedding_vector) != _EMBEDDING_DIM:
            raise ValueError(
                f"embedding_vector must have exactly {_EMBEDDING_DIM} dimensions, "
                f"got {len(embedding_vector)}."
            )

        knn_clause: dict = {
            "vector": embedding_vector,
            "k": top_k,
        }
        if filters is not None:
            knn_clause["filter"] = {"bool": {"filter": [filters]}}

        query_body = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": knn_clause,
                }
            },
        }

        try:
            response = self._client.search(index=_INDEX_NAME, body=query_body)
        except OpenSearchException as exc:
            logger.error("search_by_embedding failed: %s", exc)
            raise

        results = []
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            results.append(
                {
                    "image_id": source.get("image_id"),
                    "project_id": source.get("project_id"),
                    "tags": source.get("tags"),
                    "date": source.get("date"),
                    "location": source.get("location"),
                    "score": hit.get("_score"),
                }
            )
        return results

    def delete_image(self, image_id: str) -> dict:
        """
        Delete an image document from the index.

        Parameters
        ----------
        image_id : str
            The image_id (_id) of the document to delete.

        Returns
        -------
        dict
            The OpenSearch delete API response, or an empty dict if not found.

        Raises
        ------
        opensearchpy.OpenSearchException
            Re-raised after logging if the API call fails (excluding 404).
        """
        try:
            return self._client.delete(index=_INDEX_NAME, id=image_id)
        except NotFoundError:
            return {}
        except OpenSearchException as exc:
            logger.error("delete_image failed: %s", exc)
            raise
