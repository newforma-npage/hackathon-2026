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

Pre-filtering
-------------
``search_by_embedding`` accepts a ``SearchFilters`` dataclass that is
translated into an OpenSearch ``bool.filter`` clause applied *inside* the
kNN query so that the ANN engine only considers matching documents.

Supported filters:
  project_id  – exact match on the ``project_id`` keyword field
  date_from   – inclusive lower bound on the ``date`` date field (ISO 8601)
  date_to     – inclusive upper bound on the ``date`` date field (ISO 8601)
  tags        – one or more tag slugs that must ALL be present (terms filter)

All active filters are combined with ``bool.must`` so every condition must
be satisfied.  Passing ``SearchFilters()`` with no fields set is equivalent
to passing no filter at all.
"""

import logging
import os
import re
from dataclasses import dataclass, field

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


# ---------------------------------------------------------------------------
# Filter schema
# ---------------------------------------------------------------------------

@dataclass
class SearchFilters:
    """
    Pre-filter criteria applied inside the kNN query before ANN search.

    All non-None fields are combined with ``bool.must`` so every condition
    must be satisfied.  Fields left as ``None`` (the default) are ignored.

    Attributes
    ----------
    project_id : str | None
        Restrict results to a single project (exact keyword match).
    date_from : str | None
        Inclusive lower bound on the image date (ISO 8601, e.g. "2024-01-01").
    date_to : str | None
        Inclusive upper bound on the image date (ISO 8601, e.g. "2024-12-31").
    tags : list[str]
        Tag slugs that must ALL be present on the image.  Tags are normalised
        before the filter is built so callers may pass raw Rekognition names.
        An empty list means no tag filter is applied.
    """
    project_id: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    tags: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Return True when no filter criteria are set."""
        return (
            self.project_id is None
            and self.date_from is None
            and self.date_to is None
            and not self.tags
        )

    def to_opensearch_filter(self) -> dict | None:
        """
        Build an OpenSearch ``bool`` filter clause from the active criteria.

        Returns ``None`` when no criteria are set (caller should omit the
        filter key entirely to avoid an empty bool clause).

        Returns a ``{"bool": {"must": [...]}}`` dict otherwise, with one
        clause per active criterion:

        - ``project_id``  → ``{"term": {"project_id": <value>}}``
        - ``date_from``   → ``{"range": {"date": {"gte": <value>}}}``
        - ``date_to``     → ``{"range": {"date": {"lte": <value>}}}``
        - ``tags``        → ``{"terms": {"tags": [<normalised slugs>]}}``
          (date_from and date_to are merged into a single range clause)
        """
        if self.is_empty():
            return None

        must: list[dict] = []

        if self.project_id is not None:
            must.append({"term": {"project_id": self.project_id}})

        # Merge date bounds into a single range clause
        date_range: dict = {}
        if self.date_from is not None:
            date_range["gte"] = self.date_from
        if self.date_to is not None:
            date_range["lte"] = self.date_to
        if date_range:
            must.append({"range": {"date": date_range}})

        if self.tags:
            normalised = normalise_tags(self.tags)
            if normalised:
                must.append({"terms": {"tags": normalised}})

        return {"bool": {"must": must}} if must else None


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
        filters: "SearchFilters | None" = None,
    ) -> list[dict]:
        """
        Search for images by vector similarity with optional pre-filtering.

        Pre-filters are applied *inside* the kNN query so the ANN engine only
        considers documents that match all active criteria before ranking by
        cosine similarity.

        Parameters
        ----------
        embedding_vector : list[float]
            1536-dimensional query embedding.
        top_k : int, optional
            Maximum number of results to return (default 10).
        filters : SearchFilters | None, optional
            Structured filter criteria.  Supports:
            - ``project_id``  – exact match on the project_id keyword field
            - ``date_from``   – inclusive lower bound on the date field (ISO 8601)
            - ``date_to``     – inclusive upper bound on the date field (ISO 8601)
            - ``tags``        – list of tag slugs that must ALL be present
            Pass ``None`` or ``SearchFilters()`` to search without filtering.

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

        # Build the pre-filter from the SearchFilters schema
        if filters is not None:
            os_filter = filters.to_opensearch_filter()
            if os_filter is not None:
                knn_clause["filter"] = os_filter

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
