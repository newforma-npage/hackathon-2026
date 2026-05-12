"""
Unit tests for query_builder.build_knn_query.

Requirements: 4.3, 4.4, 7.3
"""

import pytest
from search_handler.query_builder import build_knn_query, _K_MAX, _K_DEFAULT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_VECTOR: list[float] = [0.1] * 1024


def _get_filter_clauses(query: dict) -> list:
    return query["query"]["bool"]["filter"]


def _get_must_clauses(query: dict) -> list:
    return query["query"]["bool"]["must"]


def _get_knn_clause(query: dict) -> dict:
    must = _get_must_clauses(query)
    knn_clauses = [c for c in must if "knn" in c]
    assert len(knn_clauses) == 1, "Expected exactly one knn clause in must"
    return knn_clauses[0]["knn"]


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_no_filters_returns_empty_filter_list():
    """No filters → bool.filter is an empty list."""
    query = build_knn_query(SAMPLE_VECTOR)
    assert _get_filter_clauses(query) == []


def test_none_filters_returns_empty_filter_list():
    """Explicit None filters → bool.filter is an empty list."""
    query = build_knn_query(SAMPLE_VECTOR, filters=None)
    assert _get_filter_clauses(query) == []


def test_empty_dict_filters_returns_empty_filter_list():
    """Empty dict filters → bool.filter is an empty list."""
    query = build_knn_query(SAMPLE_VECTOR, filters={})
    assert _get_filter_clauses(query) == []


def test_knn_clause_present_in_must():
    """knn clause is always present in bool.must."""
    query = build_knn_query(SAMPLE_VECTOR)
    knn = _get_knn_clause(query)
    assert "embedding" in knn
    assert knn["embedding"]["vector"] == SAMPLE_VECTOR


def test_size_equals_k():
    """Top-level size matches effective k."""
    query = build_knn_query(SAMPLE_VECTOR, k=15)
    assert query["size"] == 15


def test_default_k_is_20():
    """Default k is 20 when not specified."""
    query = build_knn_query(SAMPLE_VECTOR)
    assert query["size"] == _K_DEFAULT
    knn = _get_knn_clause(query)
    assert knn["embedding"]["k"] == _K_DEFAULT


# ---------------------------------------------------------------------------
# k capping
# ---------------------------------------------------------------------------


def test_k_above_100_is_clamped_to_100():
    """k > 100 is clamped to 100."""
    query = build_knn_query(SAMPLE_VECTOR, k=200)
    assert query["size"] == _K_MAX
    knn = _get_knn_clause(query)
    assert knn["embedding"]["k"] == _K_MAX


def test_k_exactly_100_is_not_clamped():
    """k == 100 is accepted as-is."""
    query = build_knn_query(SAMPLE_VECTOR, k=100)
    assert query["size"] == 100


def test_k_of_1_is_accepted():
    """k == 1 is a valid minimum."""
    query = build_knn_query(SAMPLE_VECTOR, k=1)
    assert query["size"] == 1


# ---------------------------------------------------------------------------
# project_id filter
# ---------------------------------------------------------------------------


def test_project_id_filter_adds_term_clause():
    """project_id filter → term entry in bool.filter."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"project_id": "PROJ-001"})
    filters = _get_filter_clauses(query)
    term_clauses = [f for f in filters if "term" in f and "project_id" in f["term"]]
    assert len(term_clauses) == 1
    assert term_clauses[0]["term"]["project_id"] == "PROJ-001"


def test_project_id_none_does_not_add_filter():
    """project_id=None → no term clause added."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"project_id": None})
    filters = _get_filter_clauses(query)
    assert not any("term" in f and "project_id" in f.get("term", {}) for f in filters)


def test_project_id_empty_string_does_not_add_filter():
    """project_id='' → no term clause added."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"project_id": ""})
    filters = _get_filter_clauses(query)
    assert not any("term" in f and "project_id" in f.get("term", {}) for f in filters)


# ---------------------------------------------------------------------------
# Date range filter
# ---------------------------------------------------------------------------


def test_date_from_and_date_to_adds_range_clause():
    """Both date_from and date_to → single range clause with gte and lte."""
    query = build_knn_query(
        SAMPLE_VECTOR,
        filters={"date_from": "2024-01-01", "date_to": "2024-06-30"},
    )
    filters = _get_filter_clauses(query)
    range_clauses = [f for f in filters if "range" in f]
    assert len(range_clauses) == 1
    date_range = range_clauses[0]["range"]["date"]
    assert date_range["gte"] == "2024-01-01"
    assert date_range["lte"] == "2024-06-30"


def test_date_from_only_adds_range_with_gte():
    """Only date_from → range clause with gte only."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"date_from": "2024-01-01"})
    filters = _get_filter_clauses(query)
    range_clauses = [f for f in filters if "range" in f]
    assert len(range_clauses) == 1
    date_range = range_clauses[0]["range"]["date"]
    assert "gte" in date_range
    assert "lte" not in date_range


def test_date_to_only_adds_range_with_lte():
    """Only date_to → range clause with lte only."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"date_to": "2024-12-31"})
    filters = _get_filter_clauses(query)
    range_clauses = [f for f in filters if "range" in f]
    assert len(range_clauses) == 1
    date_range = range_clauses[0]["range"]["date"]
    assert "lte" in date_range
    assert "gte" not in date_range


def test_no_date_filters_no_range_clause():
    """No date filters → no range clause."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"project_id": "PROJ-001"})
    filters = _get_filter_clauses(query)
    assert not any("range" in f for f in filters)


# ---------------------------------------------------------------------------
# location filter
# ---------------------------------------------------------------------------


def test_location_filter_adds_term_clause():
    """location filter → term entry in bool.filter."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"location": "Site A"})
    filters = _get_filter_clauses(query)
    term_clauses = [f for f in filters if "term" in f and "location" in f["term"]]
    assert len(term_clauses) == 1
    assert term_clauses[0]["term"]["location"] == "Site A"


def test_location_none_does_not_add_filter():
    """location=None → no term clause added."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"location": None})
    filters = _get_filter_clauses(query)
    assert not any("term" in f and "location" in f.get("term", {}) for f in filters)


# ---------------------------------------------------------------------------
# tags filter
# ---------------------------------------------------------------------------


def test_tags_filter_adds_terms_clause():
    """tags filter → terms entry in bool.filter."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"tags": ["crack", "concrete"]})
    filters = _get_filter_clauses(query)
    terms_clauses = [f for f in filters if "terms" in f]
    assert len(terms_clauses) == 1
    assert set(terms_clauses[0]["terms"]["tags"]) == {"crack", "concrete"}


def test_tags_empty_list_does_not_add_filter():
    """tags=[] → no terms clause added."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"tags": []})
    filters = _get_filter_clauses(query)
    assert not any("terms" in f for f in filters)


def test_tags_none_does_not_add_filter():
    """tags=None → no terms clause added."""
    query = build_knn_query(SAMPLE_VECTOR, filters={"tags": None})
    filters = _get_filter_clauses(query)
    assert not any("terms" in f for f in filters)


# ---------------------------------------------------------------------------
# Multiple filters (logical AND)
# ---------------------------------------------------------------------------


def test_multiple_filters_all_appear_in_filter_list():
    """All active filter dimensions appear as separate entries in bool.filter."""
    query = build_knn_query(
        SAMPLE_VECTOR,
        filters={
            "project_id": "PROJ-001",
            "date_from": "2024-01-01",
            "date_to": "2024-06-30",
            "location": "Site A",
            "tags": ["crack"],
        },
    )
    filters = _get_filter_clauses(query)
    # Expect: term(project_id), range(date), term(location), terms(tags) = 4 clauses
    assert len(filters) == 4

    clause_types = set()
    for f in filters:
        clause_types.update(f.keys())
    assert "term" in clause_types
    assert "range" in clause_types
    assert "terms" in clause_types


def test_partial_filters_only_active_dimensions_added():
    """Only non-None/non-empty filter values contribute clauses."""
    query = build_knn_query(
        SAMPLE_VECTOR,
        filters={
            "project_id": "PROJ-002",
            "date_from": None,
            "date_to": None,
            "location": "",
            "tags": [],
        },
    )
    filters = _get_filter_clauses(query)
    # Only project_id is active
    assert len(filters) == 1
    assert "term" in filters[0]
    assert "project_id" in filters[0]["term"]
