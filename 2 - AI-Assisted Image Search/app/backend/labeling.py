"""
AWS Rekognition labeling — DetectLabels + DetectModerationLabels.

Responsibilities
----------------
1. Call Rekognition DetectLabels and map the raw response to a structured Tag schema.
2. Call Rekognition DetectModerationLabels in parallel and surface any flagged content.
3. Filter labels below the confidence threshold (default 70 %).
4. Derive a human-readable AI description from the top labels.
5. Assign each label to a domain category relevant to construction / engineering
   projects (the primary use-case per the design guidelines).

Tag schema
----------
Each Tag produced by this module has the shape:

    {
        "name":        str,          # Rekognition label name, title-cased
        "slug":        str,          # lowercase, spaces → hyphens  (for indexing)
        "confidence":  float,        # 0.0 – 100.0
        "category":    str,          # one of CATEGORY_* constants below
        "parents":     list[str],    # Rekognition parent category names
        "source":      "rekognition" # always "rekognition" for traceability
    }

Categories map Rekognition's broad taxonomy to the domain vocabulary used in
the design doc's example queries ("bridge", "crane", "concrete crack", etc.).

    STRUCTURE       – structural elements: bridge, beam, column, foundation …
    EQUIPMENT       – machinery and tools: crane, excavator, scaffold …
    MATERIAL        – raw materials: concrete, steel, rebar, timber …
    DAMAGE          – defects and issues: crack, corrosion, spall, leak …
    SAFETY          – PPE, signage, hazards
    ENVIRONMENT     – site surroundings: water, vegetation, weather …
    PEOPLE          – workers, personnel
    DOCUMENT        – drawings, plans, signage with text
    GENERAL         – everything else

Usage
-----
    from labeling import RekognitionLabeler, LabelingResult

    labeler = RekognitionLabeler()
    result  = labeler.label(image_bytes)

    result.tags            # list[Tag] — filtered, categorised
    result.description     # str — natural-language summary
    result.moderation_flags # list[str] — any moderation labels detected
    result.is_flagged      # bool — True if moderation labels were found
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────

MIN_CONFIDENCE: float = float(os.getenv("REKOGNITION_MIN_CONFIDENCE", "55.0"))  # labels below this are discarded
MAX_LABELS: int = int(os.getenv("REKOGNITION_MAX_LABELS", "50"))               # max labels to request from Rekognition
DESCRIPTION_LABEL_COUNT: int = 8      # how many labels to include in the description
AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")

# ── Category constants ────────────────────────────────────────────────────────

CATEGORY_STRUCTURE  = "structure"
CATEGORY_EQUIPMENT  = "equipment"
CATEGORY_MATERIAL   = "material"
CATEGORY_DAMAGE     = "damage"
CATEGORY_SAFETY     = "safety"
CATEGORY_ENVIRONMENT = "environment"
CATEGORY_PEOPLE     = "people"
CATEGORY_DOCUMENT   = "document"
CATEGORY_GENERAL    = "general"

# Keyword → category mapping.
# Keys are lowercase substrings checked against the label name.
# Order matters: first match wins.
_CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    # Damage / defects — check before materials so "crack" beats "concrete"
    (("crack", "fracture", "spall", "corrosion", "rust", "leak", "damage",
      "defect", "deteriorat", "delamination", "efflorescence", "stain",
      "settlement", "subsidence", "erosion", "failure"), CATEGORY_DAMAGE),

    # Structural elements
    (("bridge", "beam", "column", "pier", "abutment", "deck", "girder",
      "truss", "arch", "foundation", "footing", "slab", "wall", "floor",
      "ceiling", "roof", "stair", "ramp", "tunnel", "culvert", "retaining",
      "parapet", "bearing", "joint", "anchor", "bolt", "weld", "rebar",
      "reinforcement", "structure", "structural", "frame", "framing",
      "building", "construction"), CATEGORY_STRUCTURE),

    # Equipment / machinery
    (("crane", "excavator", "bulldozer", "loader", "forklift", "scaffold",
      "lift", "hoist", "pump", "generator", "compressor", "drill",
      "machinery", "machine", "equipment", "vehicle", "truck", "backhoe",
      "grader", "paver", "roller", "compactor"), CATEGORY_EQUIPMENT),

    # Materials
    (("concrete", "steel", "timber", "wood", "asphalt", "gravel", "sand",
      "soil", "rock", "stone", "brick", "masonry", "glass", "aluminum",
      "copper", "pipe", "duct", "cable", "wire", "insulation", "membrane",
      "coating", "paint", "sealant", "mortar", "grout"), CATEGORY_MATERIAL),

    # Safety
    (("helmet", "hard hat", "vest", "harness", "ppe", "safety", "hazard",
      "warning", "caution", "barrier", "fence", "cone", "sign", "tape",
      "fire extinguisher", "first aid"), CATEGORY_SAFETY),

    # People
    (("person", "people", "worker", "engineer", "inspector", "crew",
      "human", "man", "woman", "team"), CATEGORY_PEOPLE),

    # Documents / drawings
    (("drawing", "plan", "blueprint", "document", "paper", "text",
      "diagram", "chart", "map", "label", "tag"), CATEGORY_DOCUMENT),

    # Environment / surroundings
    (("water", "river", "ocean", "lake", "rain", "flood", "mud", "dirt",
      "vegetation", "tree", "grass", "sky", "cloud", "sun", "weather",
      "outdoor", "landscape", "terrain", "ground", "earth"), CATEGORY_ENVIRONMENT),
]


def _categorise(label_name: str) -> str:
    """Return the domain category for a Rekognition label name."""
    lower = label_name.lower()
    for keywords, category in _CATEGORY_RULES:
        if any(kw in lower for kw in keywords):
            return category
    return CATEGORY_GENERAL


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Tag:
    """A single structured tag derived from one Rekognition label."""
    name:       str           # title-cased label name, e.g. "Concrete Crack"
    slug:       str           # search-friendly key, e.g. "concrete-crack"
    confidence: float         # 0.0 – 100.0
    category:   str           # one of CATEGORY_* constants
    parents:    list[str]     # Rekognition parent category names
    source:     str = "rekognition"

    @classmethod
    def from_rekognition_label(cls, label: dict) -> "Tag":
        """
        Build a Tag from a single element of Rekognition's Labels list.

        Expected shape:
            {
                "Name":       "Concrete",
                "Confidence": 98.5,
                "Parents":    [{"Name": "Building Materials"}],
                ...
            }
        """
        name = label["Name"]
        confidence = round(float(label["Confidence"]), 2)
        parents = [p["Name"] for p in label.get("Parents", [])]
        slug = name.lower().replace(" ", "-")
        category = _categorise(name)
        return cls(
            name=name,
            slug=slug,
            confidence=confidence,
            category=category,
            parents=parents,
        )

    def to_dict(self) -> dict:
        return {
            "name":       self.name,
            "slug":       self.slug,
            "confidence": self.confidence,
            "category":   self.category,
            "parents":    self.parents,
            "source":     self.source,
        }


@dataclass
class LabelingResult:
    """
    The complete output of one Rekognition labeling run for a single image.

    Attributes
    ----------
    tags : list[Tag]
        All labels that passed the confidence threshold, sorted by confidence
        descending.
    description : str
        A natural-language summary built from the top DESCRIPTION_LABEL_COUNT
        labels, suitable for storage as ai_description.
    ai_labels : list[str]
        Flat list of slugs — the format stored in the vector index and
        photo-metadata.json for backward compatibility.
    moderation_flags : list[str]
        Any moderation label names returned by DetectModerationLabels.
        Empty list if the image is clean.
    is_flagged : bool
        True if any moderation labels were detected.
    raw_labels : list[dict]
        The unmodified Rekognition Labels list, for debugging / audit.
    """
    tags:             list[Tag]
    description:      str
    ai_labels:        list[str]          # slugs, for backward compat
    moderation_flags: list[str]
    is_flagged:       bool
    raw_labels:       list[dict] = field(default_factory=list)

    def to_metadata_patch(self) -> dict:
        """
        Return a dict of fields to merge into a photo metadata record.
        Matches the shape expected by main.py and the vector store.
        """
        return {
            "ai_labels":        self.ai_labels,
            "ai_description":   self.description,
            "ai_tags":          [t.to_dict() for t in self.tags],
            "moderation_flags": self.moderation_flags,
            "is_flagged":       self.is_flagged,
        }


# ── Labeler ───────────────────────────────────────────────────────────────────

class RekognitionLabeler:
    """
    Calls AWS Rekognition DetectLabels and DetectModerationLabels on an image
    and returns a structured LabelingResult.

    Both API calls are made concurrently using a ThreadPoolExecutor to keep
    total latency close to the slower of the two calls rather than their sum.

    Parameters
    ----------
    min_confidence : float
        Labels with confidence below this value are discarded (default 70.0).
    max_labels : int
        Maximum number of labels to request from DetectLabels (default 20).
    region : str
        AWS region for the Rekognition client.
    client : optional
        Inject a pre-built boto3 Rekognition client (useful for testing).
    """

    def __init__(
        self,
        min_confidence: float = MIN_CONFIDENCE,
        max_labels: int = MAX_LABELS,
        region: str = AWS_REGION,
        client=None,
    ) -> None:
        self._min_confidence = min_confidence
        self._max_labels = max_labels
        self._client = client or boto3.client("rekognition", region_name=region)

    # ── Public API ────────────────────────────────────────────────────────────

    def label(self, image_bytes: bytes) -> LabelingResult:
        """
        Run DetectLabels and DetectModerationLabels concurrently.

        Parameters
        ----------
        image_bytes : bytes
            Raw JPEG or PNG image data.

        Returns
        -------
        LabelingResult
            Structured tags, description, and moderation flags.

        Raises
        ------
        RuntimeError
            If DetectLabels fails (the primary call). Moderation failures are
            logged as warnings and treated as a clean result to avoid blocking
            the ingestion pipeline.
        """
        image_payload = {"Bytes": image_bytes}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            labels_future = pool.submit(self._detect_labels, image_payload)
            moderation_future = pool.submit(self._detect_moderation, image_payload)

            try:
                raw_labels = labels_future.result()
            except Exception as exc:
                raise RuntimeError(f"Rekognition DetectLabels failed: {exc}") from exc

            try:
                moderation_flags = moderation_future.result()
            except Exception as exc:
                logger.warning("DetectModerationLabels failed (treating as clean): %s", exc)
                moderation_flags = []

        return self._build_result(raw_labels, moderation_flags)

    def label_from_s3(self, bucket: str, key: str) -> LabelingResult:
        """
        Run labeling directly from an S3 object reference (avoids downloading
        the image bytes to the caller).

        Parameters
        ----------
        bucket : str
            S3 bucket name.
        key : str
            S3 object key.
        """
        image_payload = {"S3Object": {"Bucket": bucket, "Name": key}}

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            labels_future = pool.submit(self._detect_labels, image_payload)
            moderation_future = pool.submit(self._detect_moderation, image_payload)

            try:
                raw_labels = labels_future.result()
            except Exception as exc:
                raise RuntimeError(f"Rekognition DetectLabels failed: {exc}") from exc

            try:
                moderation_flags = moderation_future.result()
            except Exception as exc:
                logger.warning("DetectModerationLabels failed (treating as clean): %s", exc)
                moderation_flags = []

        return self._build_result(raw_labels, moderation_flags)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _detect_labels(self, image_payload: dict) -> list[dict]:
        """Call DetectLabels and return the raw Labels list."""
        response = self._client.detect_labels(
            Image=image_payload,
            MaxLabels=self._max_labels,
            MinConfidence=self._min_confidence,
        )
        return response.get("Labels", [])

    def _detect_moderation(self, image_payload: dict) -> list[str]:
        """
        Call DetectModerationLabels and return a list of flagged label names.
        Returns an empty list if no moderation labels are found.
        """
        response = self._client.detect_moderation_labels(
            Image=image_payload,
            MinConfidence=self._min_confidence,
        )
        return [lbl["Name"] for lbl in response.get("ModerationLabels", [])]

    def _build_result(
        self,
        raw_labels: list[dict],
        moderation_flags: list[str],
    ) -> LabelingResult:
        """Map raw Rekognition output to a LabelingResult."""
        # Build Tag objects, filtering by confidence (Rekognition may return
        # labels slightly below the requested threshold in edge cases)
        tags: list[Tag] = []
        for lbl in raw_labels:
            if float(lbl.get("Confidence", 0)) >= self._min_confidence:
                tags.append(Tag.from_rekognition_label(lbl))

        # Sort by confidence descending
        tags.sort(key=lambda t: t.confidence, reverse=True)

        # Flat slug list for backward compatibility with vector store / metadata
        ai_labels = [t.slug for t in tags]

        # Natural-language description from top N labels
        description = _build_description(tags)

        if moderation_flags:
            logger.warning(
                "Image flagged for moderation: %s", ", ".join(moderation_flags)
            )

        return LabelingResult(
            tags=tags,
            description=description,
            ai_labels=ai_labels,
            moderation_flags=moderation_flags,
            is_flagged=bool(moderation_flags),
            raw_labels=raw_labels,
        )


# ── Description builder ───────────────────────────────────────────────────────

def _build_description(tags: list[Tag], max_labels: int = DESCRIPTION_LABEL_COUNT) -> str:
    """
    Build a natural-language description from the top N tags.

    Groups labels by category so the description reads more naturally:
        "Structure: Bridge, Beam. Material: Concrete, Steel. Equipment: Crane."

    Falls back to a simple comma-joined list if there are fewer than 3 tags.
    """
    if not tags:
        return "No labels detected."

    top = tags[:max_labels]

    if len(top) < 3:
        return ", ".join(t.name for t in top) + "."

    # Group by category
    by_category: dict[str, list[str]] = {}
    for tag in top:
        by_category.setdefault(tag.category, []).append(tag.name)

    # Build readable segments, capitalising the category name
    segments = []
    for category, names in by_category.items():
        label_str = ", ".join(names)
        segments.append(f"{category.title()}: {label_str}")

    return ". ".join(segments) + "."
