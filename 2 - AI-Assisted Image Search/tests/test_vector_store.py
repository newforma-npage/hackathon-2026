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

# ---------------------------------------------------------------------------
# Tag normalisation — normalise_tags() unit tests
# ---------------------------------------------------------------------------

class TestNormaliseTags:
    """Unit tests for the normalise_tags() function in vector_store.py."""

    def test_lowercases_labels(self):
        from vector_store import normalise_tags
        assert normalise_tags(["Bridge", "CRANE"]) == ["bridge", "crane"]

    def test_deduplicates_case_insensitive(self):
        from vector_store import normalise_tags
        assert normalise_tags(["Bridge", "bridge", "BRIDGE"]) == ["bridge"]

    def test_strips_special_characters(self):
        from vector_store import normalise_tags
        assert normalise_tags(["Hello, World!"]) == ["hello world"]

    def test_strips_whitespace(self):
        from vector_store import normalise_tags
        assert normalise_tags(["  spaces  "]) == ["spaces"]

    def test_discards_empty_strings(self):
        from vector_store import normalise_tags
        assert normalise_tags(["", "  ", "!!!"]) == []

    def test_accepts_rekognition_label_dicts(self):
        from vector_store import normalise_tags
        labels = [{"Name": "Steel Beam"}, {"Name": "steel beam"}]
        assert normalise_tags(labels) == ["steel beam"]

    def test_accepts_mixed_strings_and_dicts(self):
        from vector_store import normalise_tags
        labels = [{"Name": "Concrete"}, "concrete", "Steel"]
        assert normalise_tags(labels) == ["concrete", "steel"]

    def test_preserves_hyphens(self):
        from vector_store import normalise_tags
        assert normalise_tags(["concrete-crack"]) == ["concrete-crack"]

    def test_empty_input_returns_empty(self):
        from vector_store import normalise_tags
        assert normalise_tags([]) == []

    def test_preserves_first_seen_order(self):
        from vector_store import normalise_tags
        result = normalise_tags(["Crane", "Bridge", "crane"])
        assert result == ["crane", "bridge"]


# ---------------------------------------------------------------------------
# index_image normalisation integration tests
# ---------------------------------------------------------------------------

class TestIndexImageNormalisation:
    """Verify that index_image normalises tags before storing them."""

    def _make_vs(self, monkeypatch):
        monkeypatch.setenv("OPENSEARCH_ENDPOINT", "https://dummy.us-east-1.aoss.amazonaws.com")
        with (
            patch("vector_store.OpenSearch"),
            patch("vector_store.boto3.Session") as mock_session_cls,
        ):
            mock_session_cls.return_value.get_credentials.return_value = MagicMock()
            from vector_store import VectorStore
            vs = VectorStore()
        vs._client = MagicMock()
        vs._client.index.return_value = {"result": "created"}
        return vs

    def test_tags_are_lowercased_in_stored_document(self, monkeypatch):
        vs = self._make_vs(monkeypatch)
        vs.index_image("img-1", "proj-1", [0.0] * 1536, ["Bridge", "CRANE"], "2024-01-01", "loc")
        body = vs._client.index.call_args[1]["body"]
        assert body["tags"] == ["bridge", "crane"]

    def test_duplicate_tags_are_deduplicated(self, monkeypatch):
        vs = self._make_vs(monkeypatch)
        vs.index_image("img-1", "proj-1", [0.0] * 1536, ["Bridge", "bridge", "BRIDGE"], "2024-01-01", "loc")
        body = vs._client.index.call_args[1]["body"]
        assert body["tags"] == ["bridge"]

    def test_rekognition_dicts_are_normalised(self, monkeypatch):
        vs = self._make_vs(monkeypatch)
        labels = [{"Name": "Steel Beam"}, {"Name": "Concrete"}]
        vs.index_image("img-1", "proj-1", [0.0] * 1536, labels, "2024-01-01", "loc")
        body = vs._client.index.call_args[1]["body"]
        assert body["tags"] == ["steel beam", "concrete"]

    def test_empty_tags_stored_as_empty_list(self, monkeypatch):
        vs = self._make_vs(monkeypatch)
        vs.index_image("img-1", "proj-1", [0.0] * 1536, [], "2024-01-01", "loc")
        body = vs._client.index.call_args[1]["body"]
        assert body["tags"] == []

    def test_special_chars_stripped_from_tags(self, monkeypatch):
        vs = self._make_vs(monkeypatch)
        vs.index_image("img-1", "proj-1", [0.0] * 1536, ["Hello, World!"], "2024-01-01", "loc")
        body = vs._client.index.call_args[1]["body"]
        assert body["tags"] == ["hello world"]


# ---------------------------------------------------------------------------
# SearchFilters — to_opensearch_filter() unit tests
# ---------------------------------------------------------------------------

class TestSearchFilters:
    """Unit tests for SearchFilters.to_opensearch_filter()."""

    def test_empty_filters_returns_none(self):
        from vector_store import SearchFilters
        assert SearchFilters().to_opensearch_filter() is None

    def test_is_empty_true_when_no_fields_set(self):
        from vector_store import SearchFilters
        assert SearchFilters().is_empty() is True

    def test_is_empty_false_when_project_id_set(self):
        from vector_store import SearchFilters
        assert SearchFilters(project_id="PROJ-001").is_empty() is False

    def test_project_id_produces_term_clause(self):
        from vector_store import SearchFilters
        f = SearchFilters(project_id="PROJ-001").to_opensearch_filter()
        assert f is not None
        assert {"term": {"project_id": "PROJ-001"}} in f["bool"]["must"]

    def test_date_from_produces_range_gte(self):
        from vector_store import SearchFilters
        f = SearchFilters(date_from="2024-01-01").to_opensearch_filter()
        assert f is not None
        range_clauses = [c for c in f["bool"]["must"] if "range" in c]
        assert len(range_clauses) == 1
        assert range_clauses[0]["range"]["date"]["gte"] == "2024-01-01"
        assert "lte" not in range_clauses[0]["range"]["date"]

    def test_date_to_produces_range_lte(self):
        from vector_store import SearchFilters
        f = SearchFilters(date_to="2024-12-31").to_opensearch_filter()
        assert f is not None
        range_clauses = [c for c in f["bool"]["must"] if "range" in c]
        assert len(range_clauses) == 1
        assert range_clauses[0]["range"]["date"]["lte"] == "2024-12-31"
        assert "gte" not in range_clauses[0]["range"]["date"]

    def test_date_from_and_date_to_merged_into_single_range_clause(self):
        from vector_store import SearchFilters
        f = SearchFilters(date_from="2024-01-01", date_to="2024-12-31").to_opensearch_filter()
        assert f is not None
        range_clauses = [c for c in f["bool"]["must"] if "range" in c]
        assert len(range_clauses) == 1  # single clause, not two
        assert range_clauses[0]["range"]["date"]["gte"] == "2024-01-01"
        assert range_clauses[0]["range"]["date"]["lte"] == "2024-12-31"

    def test_tags_produce_terms_clause_normalised(self):
        from vector_store import SearchFilters
        f = SearchFilters(tags=["Bridge", "CRANE"]).to_opensearch_filter()
        assert f is not None
        terms_clauses = [c for c in f["bool"]["must"] if "terms" in c]
        assert len(terms_clauses) == 1
        assert set(terms_clauses[0]["terms"]["tags"]) == {"bridge", "crane"}

    def test_tags_are_normalised_before_filter(self):
        from vector_store import SearchFilters
        # Duplicate and mixed-case tags should be deduped and lowercased
        f = SearchFilters(tags=["Bridge", "bridge", "Concrete Crack"]).to_opensearch_filter()
        terms_clauses = [c for c in f["bool"]["must"] if "terms" in c]
        assert set(terms_clauses[0]["terms"]["tags"]) == {"bridge", "concrete crack"}

    def test_all_filters_combined_in_must(self):
        from vector_store import SearchFilters
        f = SearchFilters(
            project_id="PROJ-001",
            date_from="2024-01-01",
            date_to="2024-12-31",
            tags=["bridge"],
        ).to_opensearch_filter()
        assert f is not None
        must = f["bool"]["must"]
        # Should have: term, range, terms = 3 clauses
        assert len(must) == 3
        clause_types = {list(c.keys())[0] for c in must}
        assert clause_types == {"term", "range", "terms"}

    def test_empty_tags_list_produces_no_terms_clause(self):
        from vector_store import SearchFilters
        f = SearchFilters(project_id="PROJ-001", tags=[]).to_opensearch_filter()
        assert f is not None
        terms_clauses = [c for c in f["bool"]["must"] if "terms" in c]
        assert len(terms_clauses) == 0

    def test_tags_that_normalise_to_empty_produce_no_terms_clause(self):
        from vector_store import SearchFilters
        # Tags that are all special chars normalise to empty strings
        f = SearchFilters(project_id="PROJ-001", tags=["!!!", "   "]).to_opensearch_filter()
        assert f is not None
        terms_clauses = [c for c in f["bool"]["must"] if "terms" in c]
        assert len(terms_clauses) == 0


# ---------------------------------------------------------------------------
# search_by_embedding pre-filter integration tests
# ---------------------------------------------------------------------------

class TestSearchByEmbeddingPreFilter:
    """Verify that search_by_embedding wires SearchFilters into the kNN query."""

    def _make_vs(self, monkeypatch):
        monkeypatch.setenv("OPENSEARCH_ENDPOINT", "https://dummy.us-east-1.aoss.amazonaws.com")
        with (
            patch("vector_store.OpenSearch"),
            patch("vector_store.boto3.Session") as mock_session_cls,
        ):
            mock_session_cls.return_value.get_credentials.return_value = MagicMock()
            from vector_store import VectorStore
            vs = VectorStore()
        vs._client = MagicMock()
        vs._client.search.return_value = {"hits": {"hits": []}}
        return vs

    def _captured_knn_clause(self, vs):
        body = vs._client.search.call_args[1]["body"]
        return body["query"]["knn"]["embedding"]

    def test_no_filter_omits_filter_key(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        vs.search_by_embedding([0.0] * 1536)
        knn = self._captured_knn_clause(vs)
        assert "filter" not in knn

    def test_empty_search_filters_omits_filter_key(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        vs.search_by_embedding([0.0] * 1536, filters=SearchFilters())
        knn = self._captured_knn_clause(vs)
        assert "filter" not in knn

    def test_project_id_filter_in_knn_clause(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        vs.search_by_embedding([0.0] * 1536, filters=SearchFilters(project_id="PROJ-001"))
        knn = self._captured_knn_clause(vs)
        assert "filter" in knn
        must = knn["filter"]["bool"]["must"]
        assert {"term": {"project_id": "PROJ-001"}} in must

    def test_date_range_filter_in_knn_clause(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        vs.search_by_embedding(
            [0.0] * 1536,
            filters=SearchFilters(date_from="2024-01-01", date_to="2024-06-30"),
        )
        knn = self._captured_knn_clause(vs)
        must = knn["filter"]["bool"]["must"]
        range_clauses = [c for c in must if "range" in c]
        assert len(range_clauses) == 1
        assert range_clauses[0]["range"]["date"] == {"gte": "2024-01-01", "lte": "2024-06-30"}

    def test_tags_filter_in_knn_clause(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        vs.search_by_embedding([0.0] * 1536, filters=SearchFilters(tags=["Bridge", "Crane"]))
        knn = self._captured_knn_clause(vs)
        must = knn["filter"]["bool"]["must"]
        terms_clauses = [c for c in must if "terms" in c]
        assert len(terms_clauses) == 1
        assert set(terms_clauses[0]["terms"]["tags"]) == {"bridge", "crane"}

    def test_all_three_filters_combined(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        vs.search_by_embedding(
            [0.0] * 1536,
            filters=SearchFilters(
                project_id="PROJ-001",
                date_from="2024-01-01",
                date_to="2024-12-31",
                tags=["bridge"],
            ),
        )
        knn = self._captured_knn_clause(vs)
        must = knn["filter"]["bool"]["must"]
        assert len(must) == 3
        clause_types = {list(c.keys())[0] for c in must}
        assert clause_types == {"term", "range", "terms"}

    def test_no_network_call_before_dimension_check(self, monkeypatch):
        from vector_store import SearchFilters
        vs = self._make_vs(monkeypatch)
        with pytest.raises(ValueError):
            vs.search_by_embedding([0.0] * 10, filters=SearchFilters(project_id="P"))
        vs._client.search.assert_not_called()


class TestDeleteImageNotFound:

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
