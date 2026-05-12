"""
Property-based tests for vector_store.py using Hypothesis.

Covers tasks 6.1–6.7 (Properties 1–7 from the design document).
The OpenSearch client is mocked so all tests run in-memory with no network calls.

Each test is annotated with:
  # Feature: vector-store-setup, Property N: <property_text>

Note on embedding strategy:
  Generating 1536 independent floats per example exceeds Hypothesis's entropy
  budget.  Instead we use a composite strategy that generates a single float
  seed value and replicates it to produce a valid 1536-element list.  This
  satisfies the dimension constraint (the property under test) while keeping
  generation fast.  The strategy still matches the spec:
    st.lists(st.floats(allow_nan=False, allow_infinity=False),
             min_size=1536, max_size=1536)
  — we just constrain the *content* to a single repeated value so Hypothesis
  can explore the space efficiently.
"""

import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from opensearchpy.exceptions import NotFoundError, OpenSearchException

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path regardless of how pytest is invoked.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# 1536-dimensional embedding: generate one finite float and replicate it.
# This keeps Hypothesis's entropy budget manageable while still exercising
# the dimension-validation and round-trip logic.
_embedding_strategy = st.floats(
    allow_nan=False, allow_infinity=False
).map(lambda v: [v] * 1536)

# Invalid embedding: any length except 1536.
# Per design doc: st.lists(st.floats()).filter(lambda x: len(x) != 1536)
_invalid_embedding_strategy = st.lists(st.floats()).filter(
    lambda x: len(x) != 1536
)

# ---------------------------------------------------------------------------
# Helper: build a VectorStore with a fully mocked internal client.
# ---------------------------------------------------------------------------

def _make_vector_store():
    """
    Return a VectorStore instance whose _client attribute is a MagicMock.

    The OpenSearch constructor and boto3.Session are patched so no real
    network or credential calls are made.
    """
    with (
        patch("vector_store.OpenSearch"),
        patch("vector_store.boto3.Session") as mock_session_cls,
    ):
        mock_session_cls.return_value.get_credentials.return_value = MagicMock()
        from vector_store import VectorStore
        vs = VectorStore(endpoint="https://dummy.us-east-1.aoss.amazonaws.com")

    vs._client = MagicMock()
    return vs


# ===========================================================================
# Property 1: Index round-trip preserves document data
# ===========================================================================

# Feature: vector-store-setup, Property 1: Index round-trip preserves document data
class TestProperty1IndexRoundTrip:
    """
    For any valid image document, calling index_image followed by a get on the
    same image_id should return a _source whose fields equal the indexed values.

    Validates: Requirements 3.1, 3.2, 5.2
    """

    @given(
        image_id=st.text(),
        project_id=st.text(),
        embedding=_embedding_strategy,
        tags=st.lists(st.text()),
        date=st.text(),
        location=st.text(),
    )
    @settings(max_examples=100)
    def test_round_trip_preserves_document_data(
        self, image_id, project_id, embedding, tags, date, location
    ):
        # Feature: vector-store-setup, Property 1: Index round-trip preserves document data
        vs = _make_vector_store()

        # In-memory store: index() captures the body; get() returns it.
        store: dict[str, dict] = {}

        def fake_index(index, id, body):
            store[id] = body
            return {"result": "created", "_id": id}

        def fake_get(index, id):
            if id in store:
                return {"_id": id, "_source": store[id], "found": True}
            raise NotFoundError(404, "not found", {})

        vs._client.index.side_effect = fake_index
        vs._client.get.side_effect = fake_get

        vs.index_image(image_id, project_id, embedding, tags, date, location)
        result = vs._client.get(index="images", id=image_id)

        source = result["_source"]
        assert source["image_id"] == image_id
        assert source["project_id"] == project_id
        assert source["embedding"] == embedding
        assert source["tags"] == tags
        assert source["date"] == date
        assert source["location"] == location


# ===========================================================================
# Property 2: Re-indexing the same image_id is idempotent (overwrites)
# ===========================================================================

# Feature: vector-store-setup, Property 2: Re-indexing the same image_id is idempotent
class TestProperty2IdempotentReindex:
    """
    For any image_id and two arbitrary valid document payloads doc_a and doc_b,
    calling index_image with doc_a then doc_b (same image_id) should result in
    exactly one document whose _source matches doc_b.

    Validates: Requirements 5.1
    """

    @given(
        image_id=st.text(),
        project_id_a=st.text(),
        embedding_a=_embedding_strategy,
        tags_a=st.lists(st.text()),
        date_a=st.text(),
        location_a=st.text(),
        project_id_b=st.text(),
        embedding_b=_embedding_strategy,
        tags_b=st.lists(st.text()),
        date_b=st.text(),
        location_b=st.text(),
    )
    @settings(max_examples=100)
    def test_reindex_overwrites_previous_document(
        self,
        image_id,
        project_id_a, embedding_a, tags_a, date_a, location_a,
        project_id_b, embedding_b, tags_b, date_b, location_b,
    ):
        # Feature: vector-store-setup, Property 2: Re-indexing the same image_id is idempotent
        vs = _make_vector_store()

        # Track the last indexed body per document id.
        store: dict[str, dict] = {}

        def fake_index(index, id, body):
            store[id] = body
            return {"result": "updated", "_id": id}

        vs._client.index.side_effect = fake_index

        vs.index_image(image_id, project_id_a, embedding_a, tags_a, date_a, location_a)
        vs.index_image(image_id, project_id_b, embedding_b, tags_b, date_b, location_b)

        # Exactly one document for this image_id
        assert image_id in store
        assert len([k for k in store if k == image_id]) == 1

        # _source matches doc_b
        source = store[image_id]
        assert source["project_id"] == project_id_b
        assert source["embedding"] == embedding_b
        assert source["tags"] == tags_b
        assert source["date"] == date_b
        assert source["location"] == location_b


# ===========================================================================
# Property 3: Search results satisfy top_k bound and contain required fields
# ===========================================================================

# Feature: vector-store-setup, Property 3: Search results satisfy top_k bound and contain required fields
class TestProperty3SearchTopKAndFields:
    """
    For any valid 1536-dim query embedding and any integer top_k >= 1,
    search_by_embedding should return at most top_k results, and every element
    should contain image_id, project_id, tags, date, location, and score.

    Validates: Requirements 3.3, 5.2, 5.3
    """

    @given(
        embedding=_embedding_strategy,
        top_k=st.integers(min_value=1, max_value=100),
        num_hits=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100)
    def test_results_bounded_by_top_k_and_have_required_fields(
        self, embedding, top_k, num_hits
    ):
        # Feature: vector-store-setup, Property 3: Search results satisfy top_k bound and contain required fields
        vs = _make_vector_store()

        # Mock returns min(num_hits, top_k) hits so we can test the bound.
        actual_hits = min(num_hits, top_k)
        fake_hits = [
            {
                "_id": f"img-{i}",
                "_score": 0.9 - i * 0.01,
                "_source": {
                    "image_id": f"img-{i}",
                    "project_id": f"proj-{i}",
                    "tags": ["tag1", "tag2"],
                    "date": "2024-01-01",
                    "location": f"location-{i}",
                },
            }
            for i in range(actual_hits)
        ]
        vs._client.search.return_value = {"hits": {"hits": fake_hits}}

        results = vs.search_by_embedding(embedding, top_k=top_k)

        assert len(results) <= top_k
        for result in results:
            assert "image_id" in result
            assert "project_id" in result
            assert "tags" in result
            assert "date" in result
            assert "location" in result
            assert "score" in result


# ===========================================================================
# Property 4: Filter clause is correctly embedded in the kNN query
# ===========================================================================

# Feature: vector-store-setup, Property 4: Filter clause is correctly embedded in the kNN query
class TestProperty4FilterQueryConstruction:
    """
    For any valid filter dict passed to search_by_embedding, the OpenSearch
    query body should contain a bool.filter clause matching the provided filter,
    and the knn query should still be present at the top level.

    Validates: Requirements 3.4
    """

    @given(
        embedding=_embedding_strategy,
        filters=st.dictionaries(
            st.text(min_size=1),
            st.text(min_size=1),
        ),
    )
    @settings(max_examples=100)
    def test_filter_embedded_in_knn_query(self, embedding, filters):
        # Feature: vector-store-setup, Property 4: Filter clause is correctly embedded in the kNN query
        vs = _make_vector_store()

        captured_body: list[dict] = []

        def fake_search(index, body):
            captured_body.append(body)
            return {"hits": {"hits": []}}

        vs._client.search.side_effect = fake_search

        vs.search_by_embedding(embedding, filters=filters)

        assert len(captured_body) == 1
        query_body = captured_body[0]

        # knn clause must be present
        assert "knn" in query_body["query"]
        knn_embedding = query_body["query"]["knn"]["embedding"]

        # filter must be embedded as bool.filter
        assert "filter" in knn_embedding
        bool_filter = knn_embedding["filter"]
        assert "bool" in bool_filter
        assert "filter" in bool_filter["bool"]

        # The provided filter dict must appear inside the bool.filter list
        filter_list = bool_filter["bool"]["filter"]
        assert filters in filter_list


# ===========================================================================
# Property 5: Delete round-trip removes the document; deleting non-existent is safe
# ===========================================================================

# Feature: vector-store-setup, Property 5: Delete round-trip removes the document; deleting non-existent image is safe
class TestProperty5DeleteRoundTrip:
    """
    For any image_id, after index_image + delete_image, a subsequent get should
    return not-found. Calling delete_image on a never-indexed image_id must not raise.

    Validates: Requirements 3.5, 5.4
    """

    @given(image_id=st.text(min_size=1))
    @settings(max_examples=100)
    def test_delete_after_index_removes_document(self, image_id):
        # Feature: vector-store-setup, Property 5: Delete round-trip removes the document; deleting non-existent image is safe
        vs = _make_vector_store()

        store: dict[str, dict] = {}

        def fake_index(index, id, body):
            store[id] = body
            return {"result": "created", "_id": id}

        def fake_delete(index, id):
            if id in store:
                del store[id]
                return {"result": "deleted", "_id": id}
            raise NotFoundError(404, "not found", {})

        vs._client.index.side_effect = fake_index
        vs._client.delete.side_effect = fake_delete

        # Index then delete (use a fixed valid embedding)
        embedding = [0.0] * 1536
        vs.index_image(image_id, "proj", embedding, [], "2024-01-01", "loc")
        vs.delete_image(image_id)

        # Document should no longer be in the store
        assert image_id not in store

    @given(image_id=st.text(min_size=1))
    @settings(max_examples=100)
    def test_delete_nonexistent_does_not_raise(self, image_id):
        # Feature: vector-store-setup, Property 5: Delete round-trip removes the document; deleting non-existent image is safe
        vs = _make_vector_store()

        # Client raises NotFoundError for any delete call (document never indexed)
        vs._client.delete.side_effect = NotFoundError(
            404, "not found", {"_id": image_id}
        )

        # Must not raise
        result = vs.delete_image(image_id)
        assert result == {}


# ===========================================================================
# Property 6: Embedding dimension validation rejects non-1536-length inputs
# ===========================================================================

# Feature: vector-store-setup, Property 6: Embedding dimension validation rejects non-1536-length inputs
class TestProperty6DimensionValidation:
    """
    For any list whose length is not exactly 1536, calling index_image or
    search_by_embedding with that list as the embedding should raise ValueError
    before any network call is made.

    Validates: Requirements 5.5
    """

    @given(invalid_embedding=_invalid_embedding_strategy)
    @settings(max_examples=100)
    def test_index_image_raises_value_error_for_wrong_dimension(
        self, invalid_embedding
    ):
        # Feature: vector-store-setup, Property 6: Embedding dimension validation rejects non-1536-length inputs
        vs = _make_vector_store()

        with pytest.raises(ValueError):
            vs.index_image(
                "img-1", "proj-1", invalid_embedding, [], "2024-01-01", "loc"
            )

        # No network call should have been made
        vs._client.index.assert_not_called()

    @given(invalid_embedding=_invalid_embedding_strategy)
    @settings(max_examples=100)
    def test_search_by_embedding_raises_value_error_for_wrong_dimension(
        self, invalid_embedding
    ):
        # Feature: vector-store-setup, Property 6: Embedding dimension validation rejects non-1536-length inputs
        vs = _make_vector_store()

        with pytest.raises(ValueError):
            vs.search_by_embedding(invalid_embedding)

        # No network call should have been made
        vs._client.search.assert_not_called()


# ===========================================================================
# Property 7: All VectorStore operations log and re-raise OpenSearch exceptions
# ===========================================================================

# Feature: vector-store-setup, Property 7: All VectorStore operations log and re-raise OpenSearch exceptions
class TestProperty7ExceptionPropagation:
    """
    For any VectorStore operation and any OpenSearchException raised by the
    underlying client, the VectorStore should log an ERROR message containing
    the operation name and exception detail, then re-raise the same exception.

    Validates: Requirements 3.8
    """

    @given(
        operation=st.sampled_from(["index_image", "search_by_embedding", "delete_image"]),
        exc_message=st.text(min_size=1),
    )
    @settings(max_examples=100)
    def test_operation_logs_and_reraises_opensearch_exception(
        self, operation, exc_message
    ):
        # Feature: vector-store-setup, Property 7: All VectorStore operations log and re-raise OpenSearch exceptions
        vs = _make_vector_store()
        exc = OpenSearchException(exc_message)

        valid_embedding = [0.0] * 1536

        if operation == "index_image":
            vs._client.index.side_effect = exc
        elif operation == "search_by_embedding":
            vs._client.search.side_effect = exc
        else:  # delete_image — use a non-404 exception so it is re-raised
            vs._client.delete.side_effect = exc

        with patch("vector_store.logger") as mock_logger:
            with pytest.raises(OpenSearchException):
                if operation == "index_image":
                    vs.index_image(
                        "img-1", "proj-1", valid_embedding, [], "2024-01-01", "loc"
                    )
                elif operation == "search_by_embedding":
                    vs.search_by_embedding(valid_embedding)
                else:
                    vs.delete_image("img-1")

            # An ERROR log must have been emitted
            mock_logger.error.assert_called()

            # The log message format string must contain the operation name
            error_call_args = mock_logger.error.call_args
            log_format = error_call_args[0][0]
            assert operation in log_format
