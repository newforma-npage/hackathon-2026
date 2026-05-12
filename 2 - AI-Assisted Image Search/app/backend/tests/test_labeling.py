"""
Unit tests for the Rekognition labeling module.

All Rekognition API calls are mocked via unittest.mock — no real AWS calls.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from labeling import (
    RekognitionLabeler,
    Tag,
    LabelingResult,
    _categorise,
    _build_description,
    CATEGORY_STRUCTURE,
    CATEGORY_EQUIPMENT,
    CATEGORY_MATERIAL,
    CATEGORY_DAMAGE,
    CATEGORY_SAFETY,
    CATEGORY_ENVIRONMENT,
    CATEGORY_PEOPLE,
    CATEGORY_GENERAL,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_rek_label(name: str, confidence: float, parents: list[str] | None = None) -> dict:
    """Build a minimal Rekognition Labels list element."""
    return {
        "Name": name,
        "Confidence": confidence,
        "Parents": [{"Name": p} for p in (parents or [])],
        "Instances": [],
        "Aliases": [],
    }


def _make_mod_label(name: str, confidence: float = 85.0) -> dict:
    return {"Name": name, "Confidence": confidence, "ParentName": ""}


BRIDGE_LABELS = [
    _make_rek_label("Bridge",    98.5, ["Structure", "Transportation"]),
    _make_rek_label("Concrete",  95.2, ["Building Materials"]),
    _make_rek_label("Crane",     88.1, ["Equipment", "Machinery"]),
    _make_rek_label("Steel",     82.4, ["Metal", "Building Materials"]),
    _make_rek_label("Worker",    75.0, ["Person"]),
    _make_rek_label("Crack",     72.3, ["Damage"]),
]

BELOW_THRESHOLD_LABELS = [
    _make_rek_label("Bridge", 98.5),
    _make_rek_label("Fog",    55.0),   # below 70 — should be filtered
    _make_rek_label("Mist",   60.0),   # below 70 — should be filtered
]


def _make_labeler(
    detect_labels_response: list[dict] | None = None,
    detect_moderation_response: list[dict] | None = None,
) -> RekognitionLabeler:
    """Return a RekognitionLabeler with a fully mocked boto3 client."""
    mock_client = MagicMock()
    mock_client.detect_labels.return_value = {
        "Labels": detect_labels_response or BRIDGE_LABELS
    }
    mock_client.detect_moderation_labels.return_value = {
        "ModerationLabels": detect_moderation_response or []
    }
    return RekognitionLabeler(client=mock_client)


# ── Tag unit tests ────────────────────────────────────────────────────────────

class TestTagFromRekognitionLabel:
    def test_name_preserved(self):
        tag = Tag.from_rekognition_label(_make_rek_label("Concrete Crack", 91.0))
        assert tag.name == "Concrete Crack"

    def test_slug_lowercased_and_hyphenated(self):
        tag = Tag.from_rekognition_label(_make_rek_label("Steel Beam", 88.0))
        assert tag.slug == "steel-beam"

    def test_confidence_rounded(self):
        tag = Tag.from_rekognition_label(_make_rek_label("Bridge", 98.5678))
        assert tag.confidence == 98.57

    def test_parents_extracted(self):
        tag = Tag.from_rekognition_label(
            _make_rek_label("Bridge", 98.0, ["Structure", "Transportation"])
        )
        assert tag.parents == ["Structure", "Transportation"]

    def test_source_is_rekognition(self):
        tag = Tag.from_rekognition_label(_make_rek_label("Crane", 80.0))
        assert tag.source == "rekognition"

    def test_to_dict_has_all_keys(self):
        tag = Tag.from_rekognition_label(_make_rek_label("Bridge", 98.0))
        d = tag.to_dict()
        assert set(d.keys()) == {"name", "slug", "confidence", "category", "parents", "source"}


# ── Category mapping tests ────────────────────────────────────────────────────

class TestCategorise:
    @pytest.mark.parametrize("name,expected", [
        ("Bridge",          CATEGORY_STRUCTURE),
        ("Concrete Column", CATEGORY_STRUCTURE),
        ("Foundation",      CATEGORY_STRUCTURE),
        ("Crane",           CATEGORY_EQUIPMENT),
        ("Excavator",       CATEGORY_EQUIPMENT),
        ("Scaffold",        CATEGORY_EQUIPMENT),
        ("Concrete",        CATEGORY_MATERIAL),
        ("Steel",           CATEGORY_MATERIAL),
        ("Rebar",           CATEGORY_MATERIAL),
        ("Crack",           CATEGORY_DAMAGE),
        ("Corrosion",       CATEGORY_DAMAGE),
        ("Spalling",        CATEGORY_DAMAGE),
        ("Hard Hat",        CATEGORY_SAFETY),
        ("Safety Vest",     CATEGORY_SAFETY),
        ("Worker",          CATEGORY_PEOPLE),
        ("Person",          CATEGORY_PEOPLE),
        ("River",           CATEGORY_ENVIRONMENT),
        ("Vegetation",      CATEGORY_ENVIRONMENT),
        ("Banana",          CATEGORY_GENERAL),   # no matching keyword
    ])
    def test_category_assignment(self, name, expected):
        assert _categorise(name) == expected

    def test_damage_beats_material(self):
        # "Concrete Crack" contains both "concrete" (material) and "crack" (damage)
        # Damage rule must come first and win
        assert _categorise("Concrete Crack") == CATEGORY_DAMAGE

    def test_case_insensitive(self):
        assert _categorise("BRIDGE") == CATEGORY_STRUCTURE
        assert _categorise("crane") == CATEGORY_EQUIPMENT


# ── Description builder tests ─────────────────────────────────────────────────

class TestBuildDescription:
    def test_empty_tags_returns_no_labels_message(self):
        assert _build_description([]) == "No labels detected."

    def test_single_tag(self):
        tags = [Tag("Bridge", "bridge", 98.0, CATEGORY_STRUCTURE, [])]
        desc = _build_description(tags)
        assert "Bridge" in desc

    def test_two_tags_simple_format(self):
        tags = [
            Tag("Bridge", "bridge", 98.0, CATEGORY_STRUCTURE, []),
            Tag("Crane",  "crane",  88.0, CATEGORY_EQUIPMENT, []),
        ]
        desc = _build_description(tags)
        assert "Bridge" in desc
        assert "Crane" in desc

    def test_grouped_by_category(self):
        tags = [
            Tag("Bridge",   "bridge",   98.0, CATEGORY_STRUCTURE, []),
            Tag("Concrete", "concrete", 95.0, CATEGORY_MATERIAL,  []),
            Tag("Crane",    "crane",    88.0, CATEGORY_EQUIPMENT, []),
        ]
        desc = _build_description(tags)
        # Each category should appear as a segment header
        assert "Structure" in desc
        assert "Material" in desc
        assert "Equipment" in desc

    def test_respects_max_labels(self):
        tags = [
            Tag(f"Label{i}", f"label-{i}", float(90 - i), CATEGORY_GENERAL, [])
            for i in range(15)
        ]
        desc = _build_description(tags, max_labels=3)
        # Only first 3 labels should appear
        assert "Label0" in desc
        assert "Label1" in desc
        assert "Label2" in desc
        assert "Label3" not in desc

    def test_ends_with_period(self):
        tags = [Tag("Bridge", "bridge", 98.0, CATEGORY_STRUCTURE, [])]
        assert _build_description(tags).endswith(".")


# ── RekognitionLabeler integration tests ──────────────────────────────────────

class TestRekognitionLabeler:

    def test_label_returns_labeling_result(self):
        labeler = _make_labeler()
        result = labeler.label(b"fake-image-bytes")
        assert isinstance(result, LabelingResult)

    def test_tags_sorted_by_confidence_descending(self):
        labeler = _make_labeler()
        result = labeler.label(b"fake-image-bytes")
        confidences = [t.confidence for t in result.tags]
        assert confidences == sorted(confidences, reverse=True)

    def test_labels_below_threshold_filtered(self):
        labeler = _make_labeler(detect_labels_response=BELOW_THRESHOLD_LABELS)
        result = labeler.label(b"fake-image-bytes")
        slugs = result.ai_labels
        assert "bridge" in slugs
        assert "fog" not in slugs
        assert "mist" not in slugs

    def test_ai_labels_are_slugs(self):
        labeler = _make_labeler()
        result = labeler.label(b"fake-image-bytes")
        for slug in result.ai_labels:
            assert slug == slug.lower()
            assert " " not in slug

    def test_description_non_empty(self):
        labeler = _make_labeler()
        result = labeler.label(b"fake-image-bytes")
        assert result.description
        assert len(result.description) > 0

    def test_not_flagged_when_no_moderation_labels(self):
        labeler = _make_labeler(detect_moderation_response=[])
        result = labeler.label(b"fake-image-bytes")
        assert result.is_flagged is False
        assert result.moderation_flags == []

    def test_flagged_when_moderation_labels_present(self):
        labeler = _make_labeler(
            detect_moderation_response=[_make_mod_label("Explicit Nudity")]
        )
        result = labeler.label(b"fake-image-bytes")
        assert result.is_flagged is True
        assert "Explicit Nudity" in result.moderation_flags

    def test_both_api_calls_made(self):
        labeler = _make_labeler()
        labeler.label(b"fake-image-bytes")
        labeler._client.detect_labels.assert_called_once()
        labeler._client.detect_moderation_labels.assert_called_once()

    def test_detect_labels_called_with_correct_params(self):
        labeler = _make_labeler()
        labeler.label(b"abc")
        call_kwargs = labeler._client.detect_labels.call_args[1]
        assert call_kwargs["Image"] == {"Bytes": b"abc"}
        assert call_kwargs["MaxLabels"] == 20
        assert call_kwargs["MinConfidence"] == 70.0

    def test_moderation_failure_does_not_raise(self):
        """If DetectModerationLabels fails, label() should still succeed."""
        mock_client = MagicMock()
        mock_client.detect_labels.return_value = {"Labels": BRIDGE_LABELS}
        mock_client.detect_moderation_labels.side_effect = Exception("Service unavailable")
        labeler = RekognitionLabeler(client=mock_client)

        result = labeler.label(b"fake-image-bytes")
        assert result.is_flagged is False
        assert result.moderation_flags == []
        assert len(result.tags) > 0   # labels still returned

    def test_detect_labels_failure_raises_runtime_error(self):
        mock_client = MagicMock()
        mock_client.detect_labels.side_effect = Exception("Rekognition down")
        mock_client.detect_moderation_labels.return_value = {"ModerationLabels": []}
        labeler = RekognitionLabeler(client=mock_client)

        with pytest.raises(RuntimeError, match="DetectLabels failed"):
            labeler.label(b"fake-image-bytes")

    def test_empty_labels_response(self):
        labeler = _make_labeler(detect_labels_response=[])
        result = labeler.label(b"fake-image-bytes")
        assert result.tags == []
        assert result.ai_labels == []
        assert result.description == "No labels detected."

    def test_raw_labels_preserved(self):
        labeler = _make_labeler()
        result = labeler.label(b"fake-image-bytes")
        assert result.raw_labels == BRIDGE_LABELS

    def test_to_metadata_patch_shape(self):
        labeler = _make_labeler()
        result = labeler.label(b"fake-image-bytes")
        patch = result.to_metadata_patch()
        assert set(patch.keys()) == {
            "ai_labels", "ai_description", "ai_tags",
            "moderation_flags", "is_flagged",
        }
        assert isinstance(patch["ai_tags"], list)
        assert all(isinstance(t, dict) for t in patch["ai_tags"])

    def test_label_from_s3_passes_s3_object(self):
        labeler = _make_labeler()
        labeler.label_from_s3("my-bucket", "PROJ-001/photo.jpg")
        call_kwargs = labeler._client.detect_labels.call_args[1]
        assert call_kwargs["Image"] == {
            "S3Object": {"Bucket": "my-bucket", "Name": "PROJ-001/photo.jpg"}
        }

    def test_custom_confidence_threshold(self):
        """Labels between 60 and 70 should be included when threshold is lowered."""
        labels_with_low_confidence = [
            _make_rek_label("Bridge", 98.0),
            _make_rek_label("Fog",    65.0),  # would be filtered at default 70
        ]
        mock_client = MagicMock()
        mock_client.detect_labels.return_value = {"Labels": labels_with_low_confidence}
        mock_client.detect_moderation_labels.return_value = {"ModerationLabels": []}
        labeler = RekognitionLabeler(min_confidence=60.0, client=mock_client)

        result = labeler.label(b"fake-image-bytes")
        assert "fog" in result.ai_labels

    def test_multiple_moderation_flags(self):
        labeler = _make_labeler(
            detect_moderation_response=[
                _make_mod_label("Explicit Nudity"),
                _make_mod_label("Violence"),
            ]
        )
        result = labeler.label(b"fake-image-bytes")
        assert result.is_flagged is True
        assert len(result.moderation_flags) == 2
        assert "Violence" in result.moderation_flags
