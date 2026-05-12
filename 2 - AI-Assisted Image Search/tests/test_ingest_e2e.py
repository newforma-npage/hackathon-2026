"""
End-to-end tests for the Ingest → Embed → Index pipeline.

These tests use a REAL image from the sample data directory
(site-photo-01.jpg) and mock only the three AWS API calls:
  - Rekognition DetectLabels
  - Rekognition DetectModerationLabels
  - Bedrock InvokeModel (Titan Text Embeddings v2)
  - OpenSearch index_image

This means the full Python pipeline — label parsing, category mapping,
description building, embedding dimension validation, and OpenSearch
document construction — runs against real image bytes.

Run with:
    pytest tests/test_ingest_e2e.py -v

No AWS credentials or live services are required.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "Sample input data"
APP_DIR = PROJECT_ROOT / "app"

# Make both the project root and app/ importable
for p in [str(PROJECT_ROOT), str(APP_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Real image fixture
# ---------------------------------------------------------------------------

REAL_IMAGE_PATH = SAMPLE_DATA_DIR / "site-photo-01.jpg"


@pytest.fixture(scope="session")
def real_image_bytes() -> bytes:
    """
    Load the real JPEG from the sample data directory.
    Skip the test session if the file is not present (CI without assets).
    """
    if not REAL_IMAGE_PATH.exists():
        pytest.skip(f"Sample image not found: {REAL_IMAGE_PATH}")
    return REAL_IMAGE_PATH.read_bytes()


# ---------------------------------------------------------------------------
# Mock response factories
# ---------------------------------------------------------------------------

def _make_rekognition_labels_response(labels: list[dict] | None = None) -> dict:
    """Build a minimal Rekognition DetectLabels response."""
    default_labels = [
        {
            "Name": "Bridge",
            "Confidence": 98.5,
            "Parents": [{"Name": "Structure"}, {"Name": "Transportation"}],
            "Instances": [],
            "Aliases": [],
        },
        {
            "Name": "Concrete",
            "Confidence": 95.2,
            "Parents": [{"Name": "Building Materials"}],
            "Instances": [],
            "Aliases": [],
        },
        {
            "Name": "Crane",
            "Confidence": 88.1,
            "Parents": [{"Name": "Equipment"}, {"Name": "Machinery"}],
            "Instances": [],
            "Aliases": [],
        },
        {
            "Name": "Steel",
            "Confidence": 82.4,
            "Parents": [{"Name": "Metal"}, {"Name": "Building Materials"}],
            "Instances": [],
            "Aliases": [],
        },
        {
            "Name": "Worker",
            "Confidence": 75.0,
            "Parents": [{"Name": "Person"}],
            "Instances": [],
            "Aliases": [],
        },
    ]
    return {"Labels": labels if labels is not None else default_labels}


def _make_rekognition_moderation_response(labels: list[dict] | None = None) -> dict:
    return {"ModerationLabels": labels or []}


def _make_bedrock_embedding_response(dim: int = 1536) -> dict:
    """Build a minimal Bedrock InvokeModel response for Titan Text Embeddings v2."""
    embedding = [0.01 * (i % 100) for i in range(dim)]
    body_bytes = json.dumps({"embedding": embedding}).encode()

    # boto3 returns the body as a StreamingBody; we use BytesIO to simulate it
    mock_body = MagicMock()
    mock_body.read.return_value = body_bytes
    return {"body": mock_body}


def _make_opensearch_index_response(photo_id: str) -> dict:
    return {
        "_index": "images",
        "_id": photo_id,
        "result": "created",
        "_shards": {"total": 2, "successful": 1, "failed": 0},
    }


# ---------------------------------------------------------------------------
# Shared mock setup
# ---------------------------------------------------------------------------

class _MockedPipeline:
    """
    Context manager that patches all three AWS clients and exposes the mocks
    for assertion.  Returns an IngestionPipeline wired to the mocked clients.
    """

    def __init__(
        self,
        rekognition_labels=None,
        rekognition_moderation=None,
        bedrock_response=None,
        opensearch_response=None,
        photo_id: str | None = None,
    ):
        self._photo_id = photo_id or str(uuid.uuid4())
        self._rek_labels = rekognition_labels
        self._rek_mod = rekognition_moderation
        self._bedrock_resp = bedrock_response or _make_bedrock_embedding_response()
        self._os_resp = opensearch_response or _make_opensearch_index_response(self._photo_id)

        self.mock_rek_client = None
        self.mock_bedrock_client = None
        self.mock_vector_store = None
        self.pipeline = None

    def __enter__(self):
        # ── Rekognition mock ──────────────────────────────────────────────
        self.mock_rek_client = MagicMock()
        self.mock_rek_client.detect_labels.return_value = (
            _make_rekognition_labels_response(self._rek_labels)
        )
        self.mock_rek_client.detect_moderation_labels.return_value = (
            _make_rekognition_moderation_response(self._rek_mod)
        )

        # ── Bedrock mock ──────────────────────────────────────────────────
        self.mock_bedrock_client = MagicMock()
        self.mock_bedrock_client.invoke_model.return_value = self._bedrock_resp

        # ── OpenSearch / VectorStore mock ─────────────────────────────────
        self.mock_vector_store = MagicMock()
        self.mock_vector_store.index_image.return_value = self._os_resp

        # ── Build pipeline with injected mocks ────────────────────────────
        from backend.labeling import RekognitionLabeler
        from backend.embeddings import BedrockEmbeddingClient
        from backend.ingestion import IngestionPipeline

        labeler = RekognitionLabeler(client=self.mock_rek_client)
        embedder = BedrockEmbeddingClient.__new__(BedrockEmbeddingClient)
        embedder._client = self.mock_bedrock_client

        self.pipeline = IngestionPipeline(
            labeler=labeler,
            embedder=embedder,
            vector_store=self.mock_vector_store,
        )
        return self

    def __exit__(self, *args):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PHOTO_ID   = str(uuid.uuid5(uuid.NAMESPACE_URL, "site-photo-01.jpg"))
PROJECT_ID = "PROJ-001"
FILENAME   = "site-photo-01.jpg"
METADATA   = {
    "project_name": "Harbor Bridge Reconstruction",
    "location":     "Pier P-3, East Side",
    "date_taken":   "2024-04-15T08:30:00-07:00",
    "taken_by":     "John Smith",
}


# ===========================================================================
# E2E-1: Happy path — real image bytes flow through the full pipeline
# ===========================================================================

class TestHappyPath:

    def test_ingest_returns_ingestion_result(self, real_image_bytes):
        """Full pipeline completes and returns an IngestionResult."""
        from backend.ingestion import IngestionResult

        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(
                photo_id=PHOTO_ID,
                project_id=PROJECT_ID,
                filename=FILENAME,
                image_bytes=real_image_bytes,
                metadata=METADATA,
            )

        assert isinstance(result, IngestionResult)

    def test_photo_id_preserved(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
        assert result.photo_id == PHOTO_ID

    def test_ai_labels_are_slugs(self, real_image_bytes):
        """ai_labels must be lowercase hyphenated slugs."""
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        assert len(result.ai_labels) > 0
        for slug in result.ai_labels:
            assert slug == slug.lower(), f"slug not lowercase: {slug!r}"
            assert " " not in slug, f"slug contains space: {slug!r}"

    def test_ai_description_non_empty(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
        assert result.ai_description
        assert len(result.ai_description) > 0

    def test_embedding_dim_is_1536(self, real_image_bytes):
        """Vector written to OpenSearch must be 1536-dimensional."""
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
        assert result.embedding_dim == 1536

    def test_not_flagged_for_clean_image(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
        assert result.is_flagged is False
        assert result.moderation_flags == []

    def test_opensearch_result_is_created(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
        assert result.opensearch_result.get("result") == "created"

    def test_indexed_at_is_iso_string(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
        # Should parse without raising
        datetime_obj = __import__("datetime").datetime.fromisoformat(result.indexed_at)
        assert datetime_obj is not None


# ===========================================================================
# E2E-2: AWS call verification — correct params passed to each service
# ===========================================================================

class TestAwsCallVerification:

    def test_rekognition_detect_labels_called_with_real_bytes(self, real_image_bytes):
        """DetectLabels must be called with the actual image bytes."""
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        call_kwargs = ctx.mock_rek_client.detect_labels.call_args[1]
        assert call_kwargs["Image"]["Bytes"] == real_image_bytes

    def test_rekognition_detect_labels_min_confidence_70(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        call_kwargs = ctx.mock_rek_client.detect_labels.call_args[1]
        assert call_kwargs["MinConfidence"] == 70.0

    def test_rekognition_moderation_called(self, real_image_bytes):
        """DetectModerationLabels must also be called (security requirement)."""
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        ctx.mock_rek_client.detect_moderation_labels.assert_called_once()

    def test_bedrock_called_with_text_model(self, real_image_bytes):
        """Bedrock must be called with the Titan Text Embeddings v2 model."""
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        call_kwargs = ctx.mock_bedrock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v2:0"

    def test_bedrock_input_is_ai_description(self, real_image_bytes):
        """The text sent to Bedrock must be the AI description from Rekognition."""
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        call_kwargs = ctx.mock_bedrock_client.invoke_model.call_args[1]
        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == result.ai_description

    def test_opensearch_index_image_called_once(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        ctx.mock_vector_store.index_image.assert_called_once()

    def test_opensearch_receives_correct_photo_id(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        args = ctx.mock_vector_store.index_image.call_args[0]
        assert args[0] == PHOTO_ID   # first positional arg is image_id

    def test_opensearch_receives_correct_project_id(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        args = ctx.mock_vector_store.index_image.call_args[0]
        assert args[1] == PROJECT_ID  # second positional arg is project_id

    def test_opensearch_receives_1536_dim_vector(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        args = ctx.mock_vector_store.index_image.call_args[0]
        embedding = args[2]           # third positional arg is embedding
        assert len(embedding) == 1536

    def test_opensearch_receives_ai_labels_as_tags(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        args = ctx.mock_vector_store.index_image.call_args[0]
        tags = args[3]                # fourth positional arg is tags
        assert tags == result.ai_labels

    def test_opensearch_receives_date_from_metadata(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        args = ctx.mock_vector_store.index_image.call_args[0]
        date = args[4]                # fifth positional arg is date
        assert date == METADATA["date_taken"]

    def test_opensearch_receives_location_from_metadata(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        args = ctx.mock_vector_store.index_image.call_args[0]
        location = args[5]            # sixth positional arg is location
        assert location == METADATA["location"]


# ===========================================================================
# E2E-3: Label mapping — Rekognition output correctly mapped to tag schema
# ===========================================================================

class TestLabelMapping:

    def test_bridge_label_maps_to_structure_category(self, real_image_bytes):
        from backend.labeling import CATEGORY_STRUCTURE

        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        categories = {t.category for t in result.ai_tags}
        assert CATEGORY_STRUCTURE in categories

    def test_crane_label_maps_to_equipment_category(self, real_image_bytes):
        from backend.labeling import CATEGORY_EQUIPMENT

        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        categories = {t.category for t in result.ai_tags}
        assert CATEGORY_EQUIPMENT in categories

    def test_concrete_label_maps_to_material_category(self, real_image_bytes):
        from backend.labeling import CATEGORY_MATERIAL

        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        categories = {t.category for t in result.ai_tags}
        assert CATEGORY_MATERIAL in categories

    def test_all_tags_have_required_fields(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        for tag in result.ai_tags:
            assert hasattr(tag, "name")
            assert hasattr(tag, "slug")
            assert hasattr(tag, "confidence")
            assert hasattr(tag, "category")
            assert hasattr(tag, "parents")

    def test_tags_sorted_by_confidence_descending(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        confidences = [t.confidence for t in result.ai_tags]
        assert confidences == sorted(confidences, reverse=True)

    def test_low_confidence_labels_excluded(self, real_image_bytes):
        """Labels below 70 % confidence must not appear in ai_labels."""
        labels_with_low = [
            {"Name": "Bridge",  "Confidence": 98.5, "Parents": [], "Instances": [], "Aliases": []},
            {"Name": "Fog",     "Confidence": 55.0, "Parents": [], "Instances": [], "Aliases": []},
        ]
        with _MockedPipeline(photo_id=PHOTO_ID, rekognition_labels=labels_with_low) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        assert "bridge" in result.ai_labels
        assert "fog" not in result.ai_labels

    def test_description_contains_top_label_names(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        # The description should mention at least one of the top labels
        top_names = [t.name for t in result.ai_tags[:3]]
        assert any(name in result.ai_description for name in top_names)


# ===========================================================================
# E2E-4: Moderation — flagged images are rejected before indexing
# ===========================================================================

class TestModerationRejection:

    def test_flagged_image_raises_value_error(self, real_image_bytes):
        """A moderation-flagged image must raise ValueError and NOT call OpenSearch."""
        mod_labels = [{"Name": "Explicit Nudity", "Confidence": 92.0, "ParentName": ""}]

        with _MockedPipeline(photo_id=PHOTO_ID, rekognition_moderation=mod_labels) as ctx:
            with pytest.raises(ValueError, match="flagged for moderation"):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

            # OpenSearch must NOT have been called
            ctx.mock_vector_store.index_image.assert_not_called()

    def test_flagged_image_does_not_call_bedrock(self, real_image_bytes):
        """Bedrock must NOT be called if the image is flagged."""
        mod_labels = [{"Name": "Violence", "Confidence": 88.0, "ParentName": ""}]

        with _MockedPipeline(photo_id=PHOTO_ID, rekognition_moderation=mod_labels) as ctx:
            with pytest.raises(ValueError):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

            ctx.mock_bedrock_client.invoke_model.assert_not_called()

    def test_moderation_failure_does_not_block_ingest(self, real_image_bytes):
        """
        If DetectModerationLabels itself fails (service error), the pipeline
        should treat the image as clean and continue — matching the design doc's
        error handling for Error Scenario 1.
        """
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_rek_client.detect_moderation_labels.side_effect = Exception("Service unavailable")
            # Should NOT raise
            result = ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        assert result.is_flagged is False
        ctx.mock_vector_store.index_image.assert_called_once()


# ===========================================================================
# E2E-5: Error propagation — upstream failures surface as RuntimeError
# ===========================================================================

class TestErrorPropagation:

    def test_rekognition_failure_raises_runtime_error(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_rek_client.detect_labels.side_effect = Exception("Rekognition down")
            with pytest.raises(RuntimeError, match="Rekognition labeling failed"):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

    def test_bedrock_failure_raises_runtime_error(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_bedrock_client.invoke_model.side_effect = Exception("Bedrock down")
            with pytest.raises(RuntimeError, match="Bedrock embedding failed"):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

    def test_opensearch_failure_raises_runtime_error(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_vector_store.index_image.side_effect = Exception("OpenSearch down")
            with pytest.raises(RuntimeError, match="OpenSearch indexing failed"):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

    def test_rekognition_failure_does_not_call_bedrock(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_rek_client.detect_labels.side_effect = Exception("Rekognition down")
            with pytest.raises(RuntimeError):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
            ctx.mock_bedrock_client.invoke_model.assert_not_called()

    def test_bedrock_failure_does_not_call_opensearch(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_bedrock_client.invoke_model.side_effect = Exception("Bedrock down")
            with pytest.raises(RuntimeError):
                ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
            ctx.mock_vector_store.index_image.assert_not_called()


# ===========================================================================
# E2E-6: Idempotency — ingesting the same image twice calls index_image twice
#         (upsert semantics are the vector store's responsibility)
# ===========================================================================

class TestIdempotency:

    def test_double_ingest_calls_index_image_twice(self, real_image_bytes):
        """
        Calling ingest twice for the same photo_id should call index_image twice.
        The VectorStore is responsible for upsert semantics (PUT with same _id).
        """
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        assert ctx.mock_vector_store.index_image.call_count == 2

    def test_double_ingest_same_photo_id_both_times(self, real_image_bytes):
        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)
            ctx.pipeline.ingest(PHOTO_ID, PROJECT_ID, FILENAME, real_image_bytes, METADATA)

        for c in ctx.mock_vector_store.index_image.call_args_list:
            assert c[0][0] == PHOTO_ID


# ===========================================================================
# E2E-7: Multiple images — each gets its own vector store call
# ===========================================================================

class TestMultipleImages:

    def test_two_different_images_produce_two_index_calls(self, real_image_bytes):
        """
        Ingesting two different photos must result in two separate index_image calls,
        each with the correct photo_id.
        """
        photo_id_2 = str(uuid.uuid5(uuid.NAMESPACE_URL, "site-photo-02.jpg"))

        with _MockedPipeline(photo_id=PHOTO_ID) as ctx:
            ctx.mock_vector_store.index_image.side_effect = [
                _make_opensearch_index_response(PHOTO_ID),
                _make_opensearch_index_response(photo_id_2),
            ]

            ctx.pipeline.ingest(PHOTO_ID,    PROJECT_ID, "site-photo-01.jpg", real_image_bytes, METADATA)
            ctx.pipeline.ingest(photo_id_2,  PROJECT_ID, "site-photo-02.jpg", real_image_bytes, METADATA)

        assert ctx.mock_vector_store.index_image.call_count == 2

        first_call_id  = ctx.mock_vector_store.index_image.call_args_list[0][0][0]
        second_call_id = ctx.mock_vector_store.index_image.call_args_list[1][0][0]
        assert first_call_id  == PHOTO_ID
        assert second_call_id == photo_id_2
