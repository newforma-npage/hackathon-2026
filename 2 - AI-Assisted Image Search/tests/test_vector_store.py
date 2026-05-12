"""
Unit tests for vector_store.py and scripts/create_index.py.

Covers tasks 5.1–5.5:
  5.1  build_index_mapping() returns the exact mapping structure
  5.2  VectorStore.__init__ raises ValueError when no endpoint is configured
  5.3  VectorStore.__init__ uses the constructor-argument endpoint
  5.4  VectorStore.__init__ falls back to OPENSEARCH_ENDPOINT env var
  5.5  VectorStore.delete_image returns {} and does not raise on NotFoundError (404)
"""

import sys
import os
import importlib
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — make sure the project root is on sys.path so imports work
# regardless of how pytest is invoked.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# 5.1  build_index_mapping() — exact structure
# ---------------------------------------------------------------------------

class TestBuildIndexMapping:
    """Task 5.1: Verify build_index_mapping() returns the exact required structure."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "create_index",
            os.path.join(SCRIPTS_DIR, "create_index.py"),
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.build_index_mapping = module.build_index_mapping

    def test_settings_knn_is_true(self):
        mapping = self.build_index_mapping()
        assert mapping["settings"]["index.knn"] is True

    def test_image_id_is_keyword(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["image_id"]["type"] == "keyword"

    def test_project_id_is_keyword(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["project_id"]["type"] == "keyword"

    def test_tags_is_keyword(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["tags"]["type"] == "keyword"

    def test_location_is_keyword(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["location"]["type"] == "keyword"

    def test_date_is_date(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["date"]["type"] == "date"

    def test_embedding_type_is_knn_vector(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["embedding"]["type"] == "knn_vector"

    def test_embedding_dimension_is_1536(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["embedding"]["dimension"] == 1536

    def test_embedding_engine_is_faiss(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["embedding"]["method"]["engine"] == "faiss"

    def test_embedding_space_type_is_cosine(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["embedding"]["method"]["space_type"] == "cosine"

    def test_embedding_method_name_is_hnsw(self):
        mapping = self.build_index_mapping()
        assert mapping["mappings"]["properties"]["embedding"]["method"]["name"] == "hnsw"


# ---------------------------------------------------------------------------
# 5.2 – 5.4  VectorStore.__init__ endpoint resolution
# ---------------------------------------------------------------------------

# We patch both the OpenSearch client constructor and boto3.Session so that
# no real network calls or credential lookups happen.
_MOCK_OPENSEARCH_PATH = "vector_store.OpenSearch"
_MOCK_BOTO3_SESSION_PATH = "vector_store.boto3.Session"


class TestVectorStoreInit:
    """Tasks 5.2–5.4: VectorStore endpoint resolution and ValueError on missing config."""

    def _make_mock_session(self):
        """Return a mock boto3.Session whose get_credentials() returns a mock."""
        mock_session = MagicMock()
        mock_session.get_credentials.return_value = MagicMock()
        return mock_session

    # ------------------------------------------------------------------
    # 5.2  No endpoint anywhere → ValueError
    # ------------------------------------------------------------------
    def test_raises_value_error_when_no_endpoint_and_no_env_var(self, monkeypatch):
        """Task 5.2: ValueError raised when neither arg nor env var is set."""
        monkeypatch.delenv("OPENSEARCH_ENDPOINT", raising=False)

        from vector_store import VectorStore

        with pytest.raises(ValueError, match="endpoint"):
            VectorStore()

    # ------------------------------------------------------------------
    # 5.3  Constructor argument takes precedence
    # ------------------------------------------------------------------
    def test_uses_constructor_argument_endpoint(self, monkeypatch):
        """Task 5.3: Constructor arg endpoint is used when provided."""
        monkeypatch.delenv("OPENSEARCH_ENDPOINT", raising=False)

        constructor_endpoint = "https://my-collection.us-east-1.aoss.amazonaws.com"

        with (
            patch(_MOCK_OPENSEARCH_PATH) as mock_os_cls,
            patch(_MOCK_BOTO3_SESSION_PATH, return_value=self._make_mock_session()),
        ):
            from vector_store import VectorStore
            vs = VectorStore(endpoint=constructor_endpoint)

        # The OpenSearch client should have been constructed once
        mock_os_cls.assert_called_once()
        call_kwargs = mock_os_cls.call_args

        # The host passed to OpenSearch should be derived from the constructor endpoint
        hosts = call_kwargs[1].get("hosts") or call_kwargs[0][0]
        assert any(
            "my-collection.us-east-1.aoss.amazonaws.com" in h["host"]
            for h in hosts
        )

    # ------------------------------------------------------------------
    # 5.4  Falls back to OPENSEARCH_ENDPOINT env var
    # ------------------------------------------------------------------
    def test_falls_back_to_env_var_endpoint(self, monkeypatch):
        """Task 5.4: OPENSEARCH_ENDPOINT env var is used when no constructor arg given."""
        env_endpoint = "https://env-collection.us-east-1.aoss.amazonaws.com"
        monkeypatch.setenv("OPENSEARCH_ENDPOINT", env_endpoint)

        with (
            patch(_MOCK_OPENSEARCH_PATH) as mock_os_cls,
            patch(_MOCK_BOTO3_SESSION_PATH, return_value=self._make_mock_session()),
        ):
            from vector_store import VectorStore
            vs = VectorStore()  # no constructor arg

        mock_os_cls.assert_called_once()
        call_kwargs = mock_os_cls.call_args
        hosts = call_kwargs[1].get("hosts") or call_kwargs[0][0]
        assert any(
            "env-collection.us-east-1.aoss.amazonaws.com" in h["host"]
            for h in hosts
        )


# ---------------------------------------------------------------------------
# 5.5  VectorStore.delete_image — NotFoundError returns {} without raising
# ---------------------------------------------------------------------------

class TestDeleteImageNotFound:
    """Task 5.5: delete_image returns {} and does not raise on 404 NotFoundError."""

    def _make_vector_store_with_mock_client(self, monkeypatch):
        """Construct a VectorStore whose internal _client is a MagicMock."""
        monkeypatch.setenv("OPENSEARCH_ENDPOINT", "https://dummy.us-east-1.aoss.amazonaws.com")

        with (
            patch("vector_store.OpenSearch"),
            patch("vector_store.boto3.Session") as mock_session_cls,
        ):
            mock_session_cls.return_value.get_credentials.return_value = MagicMock()
            from vector_store import VectorStore
            vs = VectorStore()

        # Replace the internal client with a fresh MagicMock for fine-grained control
        vs._client = MagicMock()
        return vs

    def test_returns_empty_dict_on_not_found(self, monkeypatch):
        """delete_image returns {} when the document does not exist (404)."""
        from opensearchpy.exceptions import NotFoundError

        vs = self._make_vector_store_with_mock_client(monkeypatch)

        # Simulate a 404 NotFoundError from the OpenSearch client
        not_found_error = NotFoundError(
            404,
            "Not Found",
            {"_index": "images", "_id": "missing-id", "found": False},
        )
        vs._client.delete.side_effect = not_found_error

        result = vs.delete_image("missing-id")

        assert result == {}

    def test_does_not_raise_on_not_found(self, monkeypatch):
        """delete_image must not propagate NotFoundError."""
        from opensearchpy.exceptions import NotFoundError

        vs = self._make_vector_store_with_mock_client(monkeypatch)

        not_found_error = NotFoundError(
            404,
            "Not Found",
            {"_index": "images", "_id": "ghost", "found": False},
        )
        vs._client.delete.side_effect = not_found_error

        # Should complete without raising
        try:
            vs.delete_image("ghost")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"delete_image raised unexpectedly: {exc}")
