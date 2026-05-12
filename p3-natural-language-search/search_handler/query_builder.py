"""
query_builder.py — OpenSearch ANN query construction for the Search Handler Lambda.

Builds a filter-aware kNN query dict suitable for submission to the
``image-embeddings`` OpenSearch Serverless index.  This module is a pure
function library: it performs no I/O and makes no AWS calls, making it
straightforward to unit-test in isolation.

Requirements: 4.3, 4.4, 5.1, 7.1, 7.2, 7.3
"""

from __future__ import annotations

from typing import Any

# Maximum number of nearest neighbours the caller may request.
_K_MAX: int = 100
# Default number of nearest neighbours when the caller does not specify k.
_K_DEFAULT: int = 20


def build_knn_query(
    query_vector: list[float],
    k: int = _K_DEFAULT,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an OpenSearch ``bool`` + ``knn`` query with optional pre-filters.

    The returned dict is ready to be passed directly as the ``body`` argument
    to ``opensearch-py``'s ``client.search()``.

    Parameters
    ----------
    query_vector:
        The embedding vector produced by the Bedrock Titan text/image model.
        Must be a non-empty list of floats.
    k:
        Number of nearest neighbours to retrieve.  Defaults to 20; capped at
        100 regardless of the value supplied by the caller.
    filters:
        Optional mapping of filter dimensions to their values.  Recognised
        keys and their semantics:

        ``project_id`` (str)
            Exact-match filter on the ``project_id`` keyword field.
        ``date_from`` (str | date-like)
            Inclusive lower bound for the ``date`` range filter.
        ``date_to`` (str | date-like)
            Inclusive upper bound for the ``date`` range filter.
        ``location`` (str)
            Exact-match filter on the ``location`` keyword field.
        ``tags`` (list[str])
            Any-of filter on the ``tags`` keyword field (logical OR within
            the list; the list itself is ANDed with other filter dimensions).

        ``None`` or an empty dict means no filters are applied.

    Returns
    -------
    dict
        A complete OpenSearch query body, e.g.::

            {
                "size": 20,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"project_id": "PROJ-001"}},
                            {"range": {"date": {"gte": "2024-01-01", "lte": "2024-06-30"}}},
                        ],
                        "must": [
                            {"knn": {"embedding": {"vector": [...], "k": 20}}}
                        ]
                    }
                }
            }

    Notes
    -----
    * ``k`` is capped at :data:`_K_MAX` (100) to prevent runaway queries.
    * Filter dimensions that are absent from *filters* or whose value is
      ``None`` / empty are silently skipped — they do not add an entry to
      ``bool.filter``.
    * ``date_from`` and ``date_to`` are combined into a single ``range``
      clause; either bound may be omitted independently.
    """
    # --- Clamp k -------------------------------------------------------
    effective_k: int = min(max(int(k), 1), _K_MAX)

    # --- Build filter clauses ------------------------------------------
    filter_clauses: list[dict[str, Any]] = []

    if filters:
        # project_id — exact term match
        project_id = filters.get("project_id")
        if project_id is not None and project_id != "":
            filter_clauses.append({"term": {"project_id": project_id}})

        # date range — combine date_from / date_to into one range clause
        date_from = filters.get("date_from")
        date_to = filters.get("date_to")
        if date_from is not None or date_to is not None:
            range_bounds: dict[str, Any] = {}
            if date_from is not None:
                range_bounds["gte"] = date_from
            if date_to is not None:
                range_bounds["lte"] = date_to
            filter_clauses.append({"range": {"date": range_bounds}})

        # location — exact term match
        location = filters.get("location")
        if location is not None and location != "":
            filter_clauses.append({"term": {"location": location}})

        # tags — terms (any-of) match
        tags = filters.get("tags")
        if tags:  # falsy check covers None and empty list
            filter_clauses.append({"terms": {"tags": list(tags)}})

    # --- Build must clause (kNN) ----------------------------------------
    must_clauses: list[dict[str, Any]] = [
        {
            "knn": {
                "embedding": {
                    "vector": query_vector,
                    "k": effective_k,
                }
            }
        }
    ]

    # --- Assemble full query -------------------------------------------
    return {
        "size": effective_k,
        "query": {
            "bool": {
                "filter": filter_clauses,
                "must": must_clauses,
            }
        },
    }
