"""
Pydantic schemas for POST /search/similar request and response.
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class SimilarSearchRequest(BaseModel):
    """Body accepted by POST /search/similar."""

    image: str = Field(
        ...,
        description="Base64-encoded JPEG or PNG image bytes.",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of similar images to return (1–50, default 10).",
    )
    project_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=256,
        description="Optional project filter. When supplied, only images from this project are searched.",
    )

    @field_validator("project_id")
    @classmethod
    def project_id_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("project_id must not be blank")
        return v


# ---------------------------------------------------------------------------
# Response – individual result item
# ---------------------------------------------------------------------------

class ImageResult(BaseModel):
    """A single similar-image result enriched with metadata."""

    image_id: str
    filename: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    date_taken: Optional[str] = None
    taken_by: Optional[str] = None
    location: Optional[str] = None
    tags: Optional[List[str]] = None
    ai_description: Optional[str] = None
    ai_labels: Optional[List[str]] = None
    similarity_score: float = Field(..., ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Response – top-level envelope
# ---------------------------------------------------------------------------

class SimilarSearchResponse(BaseModel):
    """Successful response envelope for POST /search/similar."""

    query_time_ms: int = Field(..., description="Total server-side processing time in ms.")
    results: List[ImageResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Standard error envelope returned on all 4xx / 5xx responses."""

    code: str
    message: str
