"""
Vector store abstraction — supports OpenSearch k-NN (primary) and pgvector (alternate).

Schema
------
Each document stored in the vector index represents one EnrichedPhoto and carries:

  Field                 Type            Notes
  ──────────────────────────────────────────────────────────────────────────
  photo_id              keyword         UUID — primary key / document ID
  embedding             knn_vector      1024-dim (multimodal) or 1536-dim (text)
  project_id            keyword         e.g. "PROJ-001"  — pre-filter field
  project_name          text            e.g. "Harbor Bridge Reconstruction"
  filename              keyword         original filename
  date_taken            date            ISO 8601 — range filter field
  location              text            site location description
  taken_by              keyword         photographer name (excluded from search)
  ai_labels             keyword[]       Rekognition label names (lowercased)
  ai_description        text            generated natural-language description
  index_version         integer         embedding model version for reconciliation
  indexed_at            date            when AI indexing completed

Index settings
--------------
  engine:       nmslib  (OpenSearch default for k-NN)
  method:       hnsw
  space_type:   cosinesimil
  ef_construction: 512
  m:            16

These settings balance recall quality against index build time for a dataset
that starts at ~16 photos and is expected to grow to tens of thousands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

# ── Dimension constants (must match embeddings.py) ────────────────────────────
MULTIMODAL_EMBEDDING_DIM = 1024   # Titan Multimodal v1  (image / image+text)
TEXT_EMBEDDING_DIM = 1536         # Titan Text v2        (text-only queries)

# The index stores multimodal vectors (image embeddings at ingest time).
# Text queries are embedded with the text model and projected to the same
# semantic space — cosine similarity handles the cross-modal comparison.
INDEX_EMBEDDING_DIM = MULTIMODAL_EMBEDDING_DIM

INDEX_NAME = os.getenv("VECTOR_INDEX_NAME", "visual-project-intelligence")

# ── OpenSearch index mapping ──────────────────────────────────────────────────

OPENSEARCH_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "index": {
            "knn": True,                    # enable k-NN plugin
            "knn.algo_param.ef_search": 512,
            "number_of_shards": 1,
            "number_of_replicas": 1,
        }
    },
    "mappings": {
        "properties": {
            # ── Vector field ──────────────────────────────────────────────
            "embedding": {
                "type": "knn_vector",
                "dimension": INDEX_EMBEDDING_DIM,
                "method": {
                    "name": "hnsw",
                    "engine": "nmslib",
                    "space_type": "cosinesimil",
                    "parameters": {
                        "ef_construction": 512,
                        "m": 16,
                    },
                },
            },
            # ── Filterable / facet fields ─────────────────────────────────
            "photo_id":      {"type": "keyword"},
            "project_id":    {"type": "keyword"},
            "project_name":  {"type": "text", "fields": {"raw": {"type": "keyword"}}},
            "filename":      {"type": "keyword"},
            "date_taken":    {"type": "date"},
            "location":      {"type": "text"},
            "taken_by":      {"type": "keyword", "index": False},  # stored, not searched
            "ai_labels":     {"type": "keyword"},                  # exact-match filter
            "ai_description":{"type": "text"},
            "index_version": {"type": "integer"},
            "indexed_at":    {"type": "date"},
        }
    },
}

# ── pgvector DDL (alternate backend) ─────────────────────────────────────────

PGVECTOR_DDL = f"""
-- Enable pgvector extension (run once per database)
CREATE EXTENSION IF NOT EXISTS vector;

-- ── photo_embeddings table ────────────────────────────────────────────────────
-- Stores one row per indexed photo with its multimodal embedding vector and
-- all metadata needed for pre-filtering and result enrichment.
CREATE TABLE IF NOT EXISTS photo_embeddings (
    photo_id        TEXT        PRIMARY KEY,                 -- UUID
    embedding       VECTOR({INDEX_EMBEDDING_DIM}) NOT NULL,  -- Titan Multimodal v1
    project_id      TEXT        NOT NULL,
    project_name    TEXT,
    filename        TEXT        NOT NULL,
    date_taken      TIMESTAMPTZ,
    location        TEXT,
    taken_by        TEXT,                                    -- stored, not indexed
    ai_labels       TEXT[]      DEFAULT '{{}}',
    ai_description  TEXT,
    index_version   INTEGER     NOT NULL DEFAULT 1,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- HNSW index for approximate nearest-neighbour search (cosine distance)
-- ef_construction=64 and m=16 are good defaults for up to ~100K vectors.
CREATE INDEX IF NOT EXISTS photo_embeddings_hnsw_idx
    ON photo_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- B-tree indexes for pre-filter columns used in WHERE clauses
CREATE INDEX IF NOT EXISTS photo_embeddings_project_idx  ON photo_embeddings (project_id);
CREATE INDEX IF NOT EXISTS photo_embeddings_date_idx     ON photo_embeddings (date_taken);

-- GIN index for array containment queries on ai_labels
CREATE INDEX IF NOT EXISTS photo_embeddings_labels_idx
    ON photo_embeddings USING gin (ai_labels);
"""

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PhotoVector:
    """
    The unit of data written to and read from the vector store.
    Mirrors the EnrichedPhoto model from the design doc, minus the raw image bytes.
    """
    photo_id:       str
    embedding:      list[float]          # INDEX_EMBEDDING_DIM floats
    project_id:     str
    project_name:   str
    filename:       str
    date_taken:     Optional[datetime]   = None
    location:       Optional[str]        = None
    taken_by:       Optional[str]        = None
    ai_labels:      list[str]            = field(default_factory=list)
    ai_description: Optional[str]        = None
    index_version:  int                  = 1
    indexed_at:     datetime             = field(default_factory=datetime.utcnow)

    def validate(self) -> None:
        """Raise ValueError if the record violates schema invariants."""
        if len(self.embedding) != INDEX_EMBEDDING_DIM:
            raise ValueError(
                f"embedding must have {INDEX_EMBEDDING_DIM} dimensions, "
                f"got {len(self.embedding)}"
            )
        if not self.photo_id:
            raise ValueError("photo_id must not be empty")
        if not self.project_id:
            raise ValueError("project_id must not be empty")

    def to_opensearch_doc(self) -> dict[str, Any]:
        """Serialise to an OpenSearch document body."""
        return {
            "photo_id":       self.photo_id,
            "embedding":      self.embedding,
            "project_id":     self.project_id,
            "project_name":   self.project_name,
            "filename":       self.filename,
            "date_taken":     self.date_taken.isoformat() if self.date_taken else None,
            "location":       self.location,
            "taken_by":       self.taken_by,
            "ai_labels":      self.ai_labels,
            "ai_description": self.ai_description,
            "index_version":  self.index_version,
            "indexed_at":     self.indexed_at.isoformat(),
        }

    def to_pgvector_params(self) -> dict[str, Any]:
        """Serialise to a dict suitable for psycopg2 / asyncpg parameterised queries."""
        return {
            "photo_id":       self.photo_id,
            "embedding":      self.embedding,   # driver converts list → vector literal
            "project_id":     self.project_id,
            "project_name":   self.project_name,
            "filename":       self.filename,
            "date_taken":     self.date_taken,
            "location":       self.location,
            "taken_by":       self.taken_by,
            "ai_labels":      self.ai_labels,
            "ai_description": self.ai_description,
            "index_version":  self.index_version,
            "indexed_at":     self.indexed_at,
        }


@dataclass
class SearchCandidate:
    """A single result returned by a kNN query before metadata enrichment."""
    photo_id: str
    score:    float   # cosine similarity in [0.0, 1.0]


@dataclass
class SearchFilters:
    """Pre-filter criteria applied inside the vector query (not post-filter)."""
    project_ids:     Optional[list[str]]  = None
    date_from:       Optional[datetime]   = None
    date_to:         Optional[datetime]   = None
    detected_labels: Optional[list[str]]  = None


# ── OpenSearch vector store ───────────────────────────────────────────────────

class OpenSearchVectorStore:
    """
    Manages the photo_embeddings index in Amazon OpenSearch Service.

    Requires the opensearch-py package:
        pip install opensearch-py

    Environment variables
    ---------------------
    OPENSEARCH_HOST     OpenSearch domain endpoint (no trailing slash)
    OPENSEARCH_USER     HTTP basic auth username  (optional)
    OPENSEARCH_PASS     HTTP basic auth password  (optional)
    VECTOR_INDEX_NAME   Index name (default: visual-project-intelligence)
    """

    def __init__(self) -> None:
        from opensearchpy import OpenSearch, RequestsHttpConnection  # type: ignore

        host = os.environ["OPENSEARCH_HOST"]
        user = os.getenv("OPENSEARCH_USER")
        password = os.getenv("OPENSEARCH_PASS")

        http_auth = (user, password) if user and password else None

        self._client = OpenSearch(
            hosts=[host],
            http_auth=http_auth,
            use_ssl=host.startswith("https"),
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )
        self._index = INDEX_NAME

    # ── Index lifecycle ───────────────────────────────────────────────────────

    def create_index(self, delete_if_exists: bool = False) -> None:
        """Create the k-NN index with the canonical mapping."""
        if self._client.indices.exists(index=self._index):
            if delete_if_exists:
                self._client.indices.delete(index=self._index)
            else:
                return  # already exists, nothing to do

        self._client.indices.create(
            index=self._index,
            body=OPENSEARCH_INDEX_MAPPING,
        )

    # ── Write operations ──────────────────────────────────────────────────────

    def upsert(self, record: PhotoVector) -> None:
        """Insert or update a photo vector document."""
        record.validate()
        self._client.index(
            index=self._index,
            id=record.photo_id,
            body=record.to_opensearch_doc(),
        )

    def delete(self, photo_id: str) -> None:
        """Remove a photo from the index."""
        self._client.delete(index=self._index, id=photo_id, ignore=[404])

    # ── Read operations ───────────────────────────────────────────────────────

    def exists(self, photo_id: str) -> bool:
        return self._client.exists(index=self._index, id=photo_id)

    def knn_search(
        self,
        query_vector: list[float],
        k: int = 50,
        filters: Optional[SearchFilters] = None,
    ) -> list[SearchCandidate]:
        """
        Run a k-NN search with optional pre-filters.

        Parameters
        ----------
        query_vector : list[float]
            The embedding vector for the query (text or image).
        k : int
            Number of nearest neighbours to retrieve.
        filters : SearchFilters, optional
            Pre-filter criteria applied before the kNN search.

        Returns
        -------
        list[SearchCandidate]
            Sorted by cosine similarity descending.
        """
        knn_clause: dict[str, Any] = {
            "vector": query_vector,
            "k": k,
        }

        filter_clauses = _build_opensearch_filters(filters)
        if filter_clauses:
            knn_clause["filter"] = {"bool": {"must": filter_clauses}}

        body = {
            "size": k,
            "_source": {"excludes": ["embedding"]},  # don't return the vector itself
            "query": {"knn": {"embedding": knn_clause}},
        }

        response = self._client.search(index=self._index, body=body)
        return [
            SearchCandidate(
                photo_id=hit["_id"],
                score=float(hit["_score"]),
            )
            for hit in response["hits"]["hits"]
        ]


def _build_opensearch_filters(filters: Optional[SearchFilters]) -> list[dict]:
    """Convert SearchFilters into OpenSearch bool query clauses."""
    if filters is None:
        return []

    clauses: list[dict] = []

    if filters.project_ids:
        clauses.append({"terms": {"project_id": filters.project_ids}})

    date_range: dict[str, str] = {}
    if filters.date_from:
        date_range["gte"] = filters.date_from.isoformat()
    if filters.date_to:
        date_range["lte"] = filters.date_to.isoformat()
    if date_range:
        clauses.append({"range": {"date_taken": date_range}})

    if filters.detected_labels:
        clauses.append({"terms": {"ai_labels": [l.lower() for l in filters.detected_labels]}})

    return clauses


# ── pgvector store ────────────────────────────────────────────────────────────

class PgVectorStore:
    """
    Manages the photo_embeddings table in PostgreSQL with pgvector.

    Requires:
        pip install psycopg2-binary pgvector

    Environment variables
    ---------------------
    PGVECTOR_DSN    PostgreSQL connection string
                    e.g. postgresql://user:pass@host:5432/dbname
    """

    def __init__(self) -> None:
        import psycopg2  # type: ignore
        from pgvector.psycopg2 import register_vector  # type: ignore

        dsn = os.environ["PGVECTOR_DSN"]
        self._conn = psycopg2.connect(dsn)
        register_vector(self._conn)

    def create_table(self) -> None:
        """Run the DDL to create the table and indexes (idempotent)."""
        with self._conn.cursor() as cur:
            cur.execute(PGVECTOR_DDL)
        self._conn.commit()

    def upsert(self, record: PhotoVector) -> None:
        """Insert or update a photo vector row."""
        record.validate()
        p = record.to_pgvector_params()
        sql = """
            INSERT INTO photo_embeddings
                (photo_id, embedding, project_id, project_name, filename,
                 date_taken, location, taken_by, ai_labels, ai_description,
                 index_version, indexed_at)
            VALUES
                (%(photo_id)s, %(embedding)s, %(project_id)s, %(project_name)s,
                 %(filename)s, %(date_taken)s, %(location)s, %(taken_by)s,
                 %(ai_labels)s, %(ai_description)s, %(index_version)s, %(indexed_at)s)
            ON CONFLICT (photo_id) DO UPDATE SET
                embedding       = EXCLUDED.embedding,
                project_id      = EXCLUDED.project_id,
                project_name    = EXCLUDED.project_name,
                filename        = EXCLUDED.filename,
                date_taken      = EXCLUDED.date_taken,
                location        = EXCLUDED.location,
                taken_by        = EXCLUDED.taken_by,
                ai_labels       = EXCLUDED.ai_labels,
                ai_description  = EXCLUDED.ai_description,
                index_version   = EXCLUDED.index_version,
                indexed_at      = EXCLUDED.indexed_at;
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, p)
        self._conn.commit()

    def delete(self, photo_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM photo_embeddings WHERE photo_id = %s", (photo_id,))
        self._conn.commit()

    def exists(self, photo_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM photo_embeddings WHERE photo_id = %s LIMIT 1",
                (photo_id,),
            )
            return cur.fetchone() is not None

    def knn_search(
        self,
        query_vector: list[float],
        k: int = 50,
        filters: Optional[SearchFilters] = None,
    ) -> list[SearchCandidate]:
        """
        Run an approximate nearest-neighbour search using the HNSW index.

        Uses cosine distance (<=>).  Score is converted to similarity: 1 - distance.
        """
        where_clauses, params = _build_pgvector_filters(filters)
        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        sql = f"""
            SELECT photo_id,
                   1 - (embedding <=> %s::vector) AS score
            FROM   photo_embeddings
            {where_sql}
            ORDER  BY embedding <=> %s::vector
            LIMIT  %s;
        """
        all_params = [query_vector] + params + [query_vector, k]

        with self._conn.cursor() as cur:
            # SET LOCAL must be a separate call — psycopg2 does not support
            # multiple statements in a single execute()
            cur.execute("SET LOCAL hnsw.ef_search = 100")
            cur.execute(sql, all_params)
            rows = cur.fetchall()

        return [SearchCandidate(photo_id=row[0], score=float(row[1])) for row in rows]


def _build_pgvector_filters(
    filters: Optional[SearchFilters],
) -> tuple[list[str], list[Any]]:
    """Return (WHERE clauses, positional params) for pgvector queries."""
    if filters is None:
        return [], []

    clauses: list[str] = []
    params: list[Any] = []

    if filters.project_ids:
        placeholders = ", ".join(["%s"] * len(filters.project_ids))
        clauses.append(f"project_id IN ({placeholders})")
        params.extend(filters.project_ids)

    if filters.date_from:
        clauses.append("date_taken >= %s")
        params.append(filters.date_from)

    if filters.date_to:
        clauses.append("date_taken <= %s")
        params.append(filters.date_to)

    if filters.detected_labels:
        # Array containment: photo must have ALL requested labels
        clauses.append("ai_labels @> %s")
        params.append([l.lower() for l in filters.detected_labels])

    return clauses, params
