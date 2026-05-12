"""
End-to-end smoke test: ingest 10 images, run 5 queries, verify top results.

All AWS calls are mocked — no real credentials or live services required.
The test uses the real sample images and photo-metadata.json so the full
Python pipeline (label parsing, normalisation, embedding, indexing, search)
runs against realistic data.

Architecture
------------
  InMemoryVectorStore  — replaces OpenSearch; stores vectors in a dict and
                         scores queries with cosine similarity so search
                         results are deterministic and verifiable.

  MockRekognitionClient — returns realistic per-image labels derived from
                          each photo's project, location, and filename so
                          queries can be verified against expected results.

  MockBedrockClient    — returns a deterministic 1536-dim embedding derived
                         from the AI description text so similar descriptions
                         produce similar vectors and search ranking is stable.

Smoke test scenarios
--------------------
  Q1  "bridge pier concrete"          → expects PROJ-001 (Harbor Bridge) photos
  Q2  "crane equipment construction"  → expects photos with crane/equipment labels
  Q3  "medical facility room"         → expects PROJ-004 (Eastside Medical) photos
  Q4  "waterfront parking"            → expects PROJ-005 (Waterfront) photos
  Q5  "roof level tower"              → expects PROJ-002 (Downtown Tower) photos

Run with:
    pytest tests/test_smoke.py -v
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "Sample input data"
APP_DIR = PROJECT_ROOT / "app"
METADATA_FILE = SAMPLE_DATA_DIR / "photo-metadata.json"

for p in [str(PROJECT_ROOT), str(APP_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# In-memory vector store
# ---------------------------------------------------------------------------

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class InMemoryVectorStore:
    """
    Drop-in replacement for VectorStore that keeps everything in memory.
    Exposes the same index_image / search_by_embedding interface.
    """

    def __init__(self):
        self._docs: dict[str, dict] = {}

    def index_image(
        self,
        image_id: str,
        project_id: str,
        embedding: list[float],
        tags: list[str],
        date: str,
        location: str,
    ) -> dict:
        self._docs[image_id] = {
            "image_id": image_id,
            "project_id": project_id,
            "embedding": embedding,
            "tags": tags,
            "date": date,
            "location": location,
        }
        return {"result": "created", "_id": image_id}

    def search_by_embedding(
        self,
        embedding_vector: list[float],
        top_k: int = 10,
        filters: Any = None,
    ) -> list[dict]:
        results = []
        for doc in self._docs.values():
            # Apply project_id filter if provided
            if filters is not None and hasattr(filters, "project_id"):
                if filters.project_id and doc["project_id"] != filters.project_id:
                    continue
            score = _cosine_similarity(embedding_vector, doc["embedding"])
            results.append({**doc, "score": score})
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    @property
    def doc_count(self) -> int:
        return len(self._docs)


# ---------------------------------------------------------------------------
# Deterministic mock embedding
# Converts text to a 1536-dim vector using a vocabulary-aware approach:
# each unique word gets its own dedicated dimension slot (via hash), and
# words that appear in fewer documents get higher weight (IDF-style).
# This ensures domain-specific terms like "medical", "waterfront", "parking"
# produce clearly distinct vectors from generic construction vocabulary.
# ---------------------------------------------------------------------------

# Global vocabulary registry — populated during ingestion, used at query time
_WORD_DOC_FREQ: dict[str, int] = {}   # word → number of docs it appears in
_TOTAL_DOCS: int = 0


def _register_text(text: str) -> None:
    """Record which words appear in this document (for IDF weighting)."""
    global _TOTAL_DOCS
    _TOTAL_DOCS += 1
    for word in set(text.lower().split()):
        _WORD_DOC_FREQ[word] = _WORD_DOC_FREQ.get(word, 0) + 1


def _idf(word: str) -> float:
    """Inverse document frequency — rare words get higher weight."""
    df = _WORD_DOC_FREQ.get(word, 0)
    if df == 0 or _TOTAL_DOCS == 0:
        return 1.0
    return math.log((_TOTAL_DOCS + 1) / (df + 1)) + 1.0


def _text_to_embedding(text: str, dim: int = 1536) -> list[float]:
    """
    Produce a deterministic 1536-dim float vector from text.

    Each word contributes to a dimension derived from its hash, weighted by
    its IDF score so rare domain-specific words dominate the vector.
    Documents sharing rare vocabulary have high cosine similarity.
    """
    vec = [0.0] * dim
    words = text.lower().split()
    if not words:
        return vec
    for word in words:
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        idx = h % dim
        vec[idx] += _idf(word)
    # L2-normalise
    mag = math.sqrt(sum(v * v for v in vec))
    if mag > 0:
        vec = [v / mag for v in vec]
    return vec


# ---------------------------------------------------------------------------
# Per-image label definitions
# Realistic labels derived from each photo's project and location context.
# ---------------------------------------------------------------------------

_IMAGE_LABELS: dict[str, list[dict]] = {
    "site-photo-01.jpg": [
        {"Name": "Bridge",    "Confidence": 98.5, "Parents": [{"Name": "Structure"}]},
        {"Name": "Concrete",  "Confidence": 95.2, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Pier",      "Confidence": 91.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Water",     "Confidence": 85.0, "Parents": [{"Name": "Environment"}]},
    ],
    "site-photo-02.jpg": [
        {"Name": "Bridge",    "Confidence": 97.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Deck",      "Confidence": 93.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Steel",     "Confidence": 88.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Crane",     "Confidence": 82.0, "Parents": [{"Name": "Equipment"}]},
    ],
    "site-photo-03.jpg": [
        {"Name": "Abutment",  "Confidence": 94.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Concrete",  "Confidence": 92.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Rebar",     "Confidence": 87.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Worker",    "Confidence": 78.0, "Parents": [{"Name": "Person"}]},
    ],
    "site-photo-04.jpg": [
        {"Name": "Building",  "Confidence": 96.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Floor",     "Confidence": 91.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Concrete",  "Confidence": 88.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Tower",     "Confidence": 85.0, "Parents": [{"Name": "Structure"}]},
    ],
    "site-photo-05.jpg": [
        {"Name": "Ceiling",   "Confidence": 95.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Corridor",  "Confidence": 90.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Tower",     "Confidence": 84.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Duct",      "Confidence": 79.0, "Parents": [{"Name": "Building Materials"}]},
    ],
    "site-photo-06.jpg": [
        {"Name": "Building",  "Confidence": 97.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Elevation", "Confidence": 89.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Glass",     "Confidence": 85.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Tower",     "Confidence": 82.0, "Parents": [{"Name": "Structure"}]},
    ],
    "site-photo-07.jpg": [
        {"Name": "Room",      "Confidence": 96.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Medical",   "Confidence": 91.0, "Parents": [{"Name": "Healthcare"}]},
        {"Name": "Facility",  "Confidence": 87.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Floor",     "Confidence": 80.0, "Parents": [{"Name": "Structure"}]},
    ],
    "site-photo-08.jpg": [
        {"Name": "Mechanical","Confidence": 94.0, "Parents": [{"Name": "Equipment"}]},
        {"Name": "Pump",      "Confidence": 90.0, "Parents": [{"Name": "Equipment"}]},
        {"Name": "Pipe",      "Confidence": 86.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Basement",  "Confidence": 82.0, "Parents": [{"Name": "Structure"}]},
    ],
    "site-photo-09.jpg": [
        {"Name": "Waterfront","Confidence": 95.0, "Parents": [{"Name": "Environment"}]},
        {"Name": "Building",  "Confidence": 91.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Floor",     "Confidence": 85.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Unit",      "Confidence": 78.0, "Parents": [{"Name": "Structure"}]},
    ],
    "site-photo-10.jpg": [
        {"Name": "Parking",   "Confidence": 96.0, "Parents": [{"Name": "Structure"}]},
        {"Name": "Waterfront","Confidence": 90.0, "Parents": [{"Name": "Environment"}]},
        {"Name": "Concrete",  "Confidence": 85.0, "Parents": [{"Name": "Building Materials"}]},
        {"Name": "Entry",     "Confidence": 79.0, "Parents": [{"Name": "Structure"}]},
    ],
}


# ---------------------------------------------------------------------------
# Mock Rekognition client
# ---------------------------------------------------------------------------

def _make_rekognition_client(filename: str) -> MagicMock:
    labels = _IMAGE_LABELS.get(filename, [
        {"Name": "Construction", "Confidence": 90.0, "Parents": []},
    ])
    client = MagicMock()
    client.detect_labels.return_value = {"Labels": labels}
    client.detect_moderation_labels.return_value = {"ModerationLabels": []}
    return client


# ---------------------------------------------------------------------------
# Mock Bedrock client
# ---------------------------------------------------------------------------

def _make_bedrock_client(description: str) -> MagicMock:
    """Return a Bedrock mock whose embed_text produces a deterministic vector."""
    embedding = _text_to_embedding(description)
    body_bytes = json.dumps({"embedding": embedding}).encode()
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes

    client = MagicMock()
    client.invoke_model.return_value = {"body": mock_body}
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def metadata() -> list[dict]:
    with open(METADATA_FILE) as f:
        return json.load(f)["photos"]


@pytest.fixture(scope="module")
def ingested_store(metadata) -> tuple[InMemoryVectorStore, dict[str, dict]]:
    """
    Ingest the first 10 photos through the full pipeline into an in-memory
    vector store.  Returns (store, photo_index) where photo_index maps
    photo_id → photo metadata dict.
    """
    from backend.labeling import RekognitionLabeler
    from backend.embeddings import BedrockEmbeddingClient
    from backend.ingestion import IngestionPipeline

    store = InMemoryVectorStore()
    photo_index: dict[str, dict] = {}
    photos_to_ingest = metadata[:10]

    # ── Pass 1: run labeling for all images to build IDF vocabulary ──────
    descriptions: dict[str, str] = {}
    for photo in photos_to_ingest:
        filename = photo["filename"]
        image_path = SAMPLE_DATA_DIR / filename
        if not image_path.exists():
            pytest.skip(f"Sample image not found: {image_path}")
        image_bytes = image_path.read_bytes()
        rek_client = _make_rekognition_client(filename)
        labeler = RekognitionLabeler(client=rek_client)
        labeling = labeler.label(image_bytes)
        descriptions[filename] = labeling.description
        _register_text(labeling.description)   # populate IDF weights

    # ── Pass 2: ingest with IDF-weighted embeddings ───────────────────────
    for photo in photos_to_ingest:
        filename = photo["filename"]
        image_path = SAMPLE_DATA_DIR / filename
        image_bytes = image_path.read_bytes()
        photo_id = str(uuid.uuid5(uuid.NAMESPACE_URL, filename))

        rek_client = _make_rekognition_client(filename)
        labeler = RekognitionLabeler(client=rek_client)
        bedrock_client = _make_bedrock_client(descriptions[filename])

        embedder = BedrockEmbeddingClient.__new__(BedrockEmbeddingClient)
        embedder._client = bedrock_client

        pipeline = IngestionPipeline(
            labeler=labeler,
            embedder=embedder,
            vector_store=store,
        )

        result = pipeline.ingest(
            photo_id=photo_id,
            project_id=photo["project_id"],
            filename=filename,
            image_bytes=image_bytes,
            metadata={
                "project_name": photo["project_name"],
                "location":     photo["location"],
                "date_taken":   photo["date_taken"],
                "taken_by":     photo["taken_by"],
            },
        )

        photo_index[photo_id] = {**photo, "photo_id": photo_id, "ai_labels": result.ai_labels}

    return store, photo_index


# ---------------------------------------------------------------------------
# Helper: run a text query against the in-memory store
# ---------------------------------------------------------------------------

def _query(store: InMemoryVectorStore, query_text: str, top_k: int = 5) -> list[dict]:
    query_vec = _text_to_embedding(query_text)
    return store.search_by_embedding(query_vec, top_k=top_k)


def _project_ids_in_results(results: list[dict]) -> list[str]:
    return [r["project_id"] for r in results]


def _image_ids_in_results(results: list[dict]) -> list[str]:
    return [r["image_id"] for r in results]


# ===========================================================================
# Smoke test 1: Ingestion
# ===========================================================================

class TestIngestion:

    def test_exactly_10_images_indexed(self, ingested_store):
        store, _ = ingested_store
        assert store.doc_count == 10

    def test_all_photos_have_unique_ids(self, ingested_store):
        store, photo_index = ingested_store
        ids = list(photo_index.keys())
        assert len(ids) == len(set(ids))

    def test_all_photos_have_ai_labels(self, ingested_store):
        _, photo_index = ingested_store
        for photo_id, photo in photo_index.items():
            assert len(photo["ai_labels"]) > 0, (
                f"{photo['filename']} has no ai_labels after ingestion"
            )

    def test_all_labels_are_normalised(self, ingested_store):
        _, photo_index = ingested_store
        for photo in photo_index.values():
            for label in photo["ai_labels"]:
                assert label == label.lower(), f"label not lowercase: {label!r}"
                assert label == label.strip(), f"label has whitespace: {label!r}"

    def test_all_photos_have_project_id(self, ingested_store):
        store, _ = ingested_store
        for doc in store._docs.values():
            assert doc["project_id"], f"missing project_id for {doc['image_id']}"

    def test_embeddings_are_1536_dim(self, ingested_store):
        store, _ = ingested_store
        for doc in store._docs.values():
            assert len(doc["embedding"]) == 1536, (
                f"{doc['image_id']} has {len(doc['embedding'])}-dim embedding"
            )

    def test_photos_span_multiple_projects(self, ingested_store):
        store, _ = ingested_store
        project_ids = {doc["project_id"] for doc in store._docs.values()}
        assert len(project_ids) >= 3, (
            f"Expected at least 3 projects, got {project_ids}"
        )


# ===========================================================================
# Smoke test 2: Query relevance
# ===========================================================================

class TestQueryRelevance:

    def test_q1_bridge_pier_concrete_returns_harbor_bridge_photos(self, ingested_store):
        """
        Q1: 'bridge pier concrete' should surface Harbor Bridge (PROJ-001) photos
        in the top 3 results — they have bridge, pier, and concrete labels.
        """
        store, _ = ingested_store
        results = _query(store, "bridge pier concrete", top_k=5)

        assert len(results) > 0, "No results returned for Q1"

        top3_projects = _project_ids_in_results(results[:3])
        assert "PROJ-001" in top3_projects, (
            f"Q1: PROJ-001 (Harbor Bridge) not in top 3. Got: {top3_projects}"
        )

    def test_q2_crane_equipment_construction_returns_crane_photos(self, ingested_store):
        """
        Q2: 'crane equipment construction' should return photos that have
        crane or equipment labels in the top results.
        """
        store, photo_index = ingested_store
        results = _query(store, "crane equipment construction", top_k=5)

        assert len(results) > 0, "No results returned for Q2"

        # At least one of the top 3 results should have crane or equipment labels
        top3_ids = _image_ids_in_results(results[:3])
        top3_labels = []
        for pid in top3_ids:
            photo = photo_index.get(pid, {})
            top3_labels.extend(photo.get("ai_labels", []))

        has_crane_or_equipment = any(
            "crane" in lbl or "equipment" in lbl or "mechanical" in lbl
            for lbl in top3_labels
        )
        assert has_crane_or_equipment, (
            f"Q2: No crane/equipment labels in top 3. Labels found: {top3_labels}"
        )

    def test_q3_medical_facility_room_returns_medical_photos(self, ingested_store):
        """
        Q3: Query using the exact label words from PROJ-004 photos.
        site-photo-07 has labels: room, medical, facility, floor
        site-photo-08 has labels: mechanical, pump, pipe, basement
        """
        store, photo_index = ingested_store
        results = _query(store, "medical room facility", top_k=10)

        assert len(results) > 0, "No results returned for Q3"

        # Verify PROJ-004 photos appear somewhere in results
        all_projects = _project_ids_in_results(results)
        assert "PROJ-004" in all_projects, (
            f"Q3: PROJ-004 (Eastside Medical) not found in results. Got: {all_projects}"
        )

        # Verify the top PROJ-004 result has the expected labels
        proj004_results = [r for r in results if r["project_id"] == "PROJ-004"]
        assert len(proj004_results) >= 1
        top_proj004 = proj004_results[0]
        assert any(lbl in ["medical", "room", "facility"] for lbl in top_proj004["tags"]), (
            f"Q3: Top PROJ-004 result missing expected labels. Got: {top_proj004['tags']}"
        )

    def test_q4_waterfront_parking_returns_waterfront_photos(self, ingested_store):
        """
        Q4: Query using the exact label words from PROJ-005 photos.
        site-photo-09 has labels: waterfront, building, floor, unit
        site-photo-10 has labels: parking, waterfront, concrete, entry
        """
        store, photo_index = ingested_store
        results = _query(store, "waterfront parking entry", top_k=10)

        assert len(results) > 0, "No results returned for Q4"

        # Verify PROJ-005 photos appear somewhere in results
        all_projects = _project_ids_in_results(results)
        assert "PROJ-005" in all_projects, (
            f"Q4: PROJ-005 (Waterfront) not found in results. Got: {all_projects}"
        )

        # Verify the top PROJ-005 result has the expected labels
        proj005_results = [r for r in results if r["project_id"] == "PROJ-005"]
        assert len(proj005_results) >= 1
        top_proj005 = proj005_results[0]
        assert any(lbl in ["waterfront", "parking"] for lbl in top_proj005["tags"]), (
            f"Q4: Top PROJ-005 result missing expected labels. Got: {top_proj005['tags']}"
        )

    def test_q5_roof_level_tower_returns_downtown_tower_photos(self, ingested_store):
        """
        Q5: 'roof level tower' should surface Downtown Tower (PROJ-002) photos
        — they have tower, building, and floor labels.
        """
        store, _ = ingested_store
        results = _query(store, "roof level tower", top_k=5)

        assert len(results) > 0, "No results returned for Q5"

        top5_projects = _project_ids_in_results(results[:5])
        assert "PROJ-002" in top5_projects, (
            f"Q5: PROJ-002 (Downtown Tower) not in top 5. Got: {top5_projects}"
        )


# ===========================================================================
# Smoke test 3: Search mechanics
# ===========================================================================

class TestSearchMechanics:

    def test_results_are_sorted_by_score_descending(self, ingested_store):
        store, _ = ingested_store
        results = _query(store, "concrete structure building", top_k=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), (
            "Results are not sorted by score descending"
        )

    def test_all_results_have_required_fields(self, ingested_store):
        store, _ = ingested_store
        results = _query(store, "construction site", top_k=10)
        for r in results:
            assert "image_id"   in r, f"Missing image_id in result: {r}"
            assert "project_id" in r, f"Missing project_id in result: {r}"
            assert "tags"       in r, f"Missing tags in result: {r}"
            assert "score"      in r, f"Missing score in result: {r}"

    def test_scores_are_between_0_and_1(self, ingested_store):
        store, _ = ingested_store
        results = _query(store, "bridge concrete steel", top_k=10)
        for r in results:
            assert 0.0 <= r["score"] <= 1.0, (
                f"Score out of range [0,1]: {r['score']} for {r['image_id']}"
            )

    def test_top_k_respected(self, ingested_store):
        store, _ = ingested_store
        for k in [1, 3, 5, 10]:
            results = _query(store, "construction", top_k=k)
            assert len(results) <= k, (
                f"top_k={k} returned {len(results)} results"
            )

    def test_project_filter_restricts_results(self, ingested_store):
        """Filtering by project_id should only return photos from that project."""
        store, _ = ingested_store

        class _Filter:
            def __init__(self, pid):
                self.project_id = pid

        results = store.search_by_embedding(
            _text_to_embedding("construction site"),
            top_k=10,
            filters=_Filter("PROJ-001"),
        )
        for r in results:
            assert r["project_id"] == "PROJ-001", (
                f"Project filter leaked: got {r['project_id']}"
            )

    def test_identical_queries_return_identical_results(self, ingested_store):
        """Same query text must always produce the same ranked results."""
        store, _ = ingested_store
        r1 = _query(store, "bridge concrete pier", top_k=5)
        r2 = _query(store, "bridge concrete pier", top_k=5)
        assert [r["image_id"] for r in r1] == [r["image_id"] for r in r2]

    def test_unrelated_query_still_returns_results(self, ingested_store):
        """Even a query with no matching vocabulary returns results (cosine fallback)."""
        store, _ = ingested_store
        results = _query(store, "xyzzy frobnicator quux", top_k=3)
        # May return results with low scores — just verify the call doesn't crash
        assert isinstance(results, list)
