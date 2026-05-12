"""
create_index.py — Create the 'images' index in an OpenSearch Serverless collection.

This script creates the OpenSearch index with the exact field mapping required by the
Visual Project Intelligence Search system. It is idempotent: if the index already exists,
it logs a message and exits cleanly without raising an error.

Usage
-----
    # Using an environment variable:
    export OPENSEARCH_ENDPOINT=https://<collection-id>.us-east-1.aoss.amazonaws.com
    python scripts/create_index.py

    # Overriding the endpoint via CLI argument:
    python scripts/create_index.py https://<collection-id>.us-east-1.aoss.amazonaws.com

Prerequisites
-------------
    pip install opensearch-py boto3

AWS credentials must be configured (e.g., via environment variables, ~/.aws/credentials,
or an IAM role) with permissions to access the OpenSearch Serverless collection.
"""

import logging
import os
import sys

import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import RequestError

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
INDEX_NAME = "images"
AWS_REGION = "us-east-1"
AOSS_SERVICE = "aoss"


def build_index_mapping() -> dict:
    """Return the index settings and mappings dict for the 'images' index.

    Returns
    -------
    dict
        A dict containing ``settings`` and ``mappings`` suitable for passing
        directly to ``client.indices.create(body=...)``.
    """
    return {
        "settings": {
            "index.knn": True
        },
        "mappings": {
            "properties": {
                "image_id": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": 1536,
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "space_type": "cosine",
                    },
                },
                "tags": {"type": "keyword"},
                "date": {"type": "date"},
                "location": {"type": "keyword"},
            }
        },
    }


def _get_endpoint() -> str:
    """Resolve the OpenSearch Serverless endpoint.

    Checks ``sys.argv[1]`` first, then falls back to the ``OPENSEARCH_ENDPOINT``
    environment variable.

    Returns
    -------
    str
        The collection endpoint URL.

    Raises
    ------
    SystemExit
        If neither source provides an endpoint.
    """
    if len(sys.argv) > 1:
        return sys.argv[1].rstrip("/")

    endpoint = os.environ.get("OPENSEARCH_ENDPOINT", "").rstrip("/")
    if not endpoint:
        logger.error(
            "No endpoint provided. Set the OPENSEARCH_ENDPOINT environment variable "
            "or pass the endpoint as the first CLI argument."
        )
        sys.exit(1)

    return endpoint


def _build_client(endpoint: str) -> OpenSearch:
    """Build an authenticated OpenSearch client for OpenSearch Serverless.

    Parameters
    ----------
    endpoint : str
        The collection endpoint URL (without trailing slash).

    Returns
    -------
    OpenSearch
        A configured ``opensearchpy.OpenSearch`` client instance.
    """
    session = boto3.Session()
    credentials = session.get_credentials()
    auth = AWSV4SignerAuth(credentials, AWS_REGION, AOSS_SERVICE)

    # Strip the scheme for the host parameter; opensearch-py adds it back.
    host = endpoint.replace("https://", "").replace("http://", "")

    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=auth,
        use_ssl=True,
        verify_certs=True,
        connection_class=RequestsHttpConnection,
        pool_maxsize=10,
    )
    return client


def create_index(client: OpenSearch) -> None:
    """Create the 'images' index using the standard field mapping.

    If the index already exists, logs an INFO message and returns without error.

    Parameters
    ----------
    client : OpenSearch
        An authenticated OpenSearch client.
    """
    try:
        response = client.indices.create(index=INDEX_NAME, body=build_index_mapping())
        logger.info("Index '%s' created successfully. Response: %s", INDEX_NAME, response)
    except RequestError as exc:
        # OpenSearch Serverless returns 400 with resource_already_exists_exception
        # when the index already exists.
        already_exists = (
            exc.status_code == 400
            or getattr(exc, "error", "") == "resource_already_exists_exception"
            or "resource_already_exists_exception" in str(exc).lower()
        )
        if already_exists:
            logger.info("Index '%s' already exists, skipping creation.", INDEX_NAME)
        else:
            logger.error(
                "Failed to create index '%s': %s", INDEX_NAME, exc, exc_info=True
            )
            raise
    except Exception as exc:
        logger.error(
            "Unexpected error while creating index '%s': %s", INDEX_NAME, exc, exc_info=True
        )
        raise


if __name__ == "__main__":
    endpoint = _get_endpoint()
    logger.info("Using OpenSearch endpoint: %s", endpoint)

    client = _build_client(endpoint)
    create_index(client)
