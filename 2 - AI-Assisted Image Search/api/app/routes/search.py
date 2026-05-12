"""
POST /search/similar — similarity search endpoint (P5).

Flow:
  1. Validate request (image, top_k, project_id)
  2. Decode + validate image bytes (format, size)
  3. Embed image via AWS Bedrock (embedding.py)
  4. Run ANN search via shared search core (search_core.py)
  5. Enrich results with metadata from OpenSearch (metadata.py)
  6. Return ranked results
"""

from __future__ import annotations

import base64
import binascii
import logging
import struct
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.auth import require_api_key
from app.models.schemas import (
    ErrorResponse,
    ImageResult,
    SimilarSearchRequest,
    SimilarSearchResponse,
)
from app.services.embedding import EmbeddingError, embed_image
from app.services.metadata import enrich_results
from app.services.search_core import SearchCoreError, run_similarity_search

logger = logging.getLogger(__name__)

router = APIRouter()

# Max decoded image size: 5 MB
MAX_IMAGE_BYTES = 5 * 1024 * 1024

# JPEG magic bytes: FF D8 FF
_JPEG_MAGIC = b"\xff\xd8\xff"
# PNG magic bytes: 89 50 4E 47 0D 0A 1A 0A
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(code=code, message=message).model_dump(),
    )


def _detect_image_format(data: bytes) -> Optional[str]:
    """Return 'jpeg', 'png', or None if the format is not recognised."""
    if data[:3] == _JPEG_MAGIC:
        return "jpeg"
    if data[:8] == _PNG_MAGIC:
        return "png"
    return None


@router.post(
    "/search/similar",
    response_model=SimilarSearchResponse,
    dependencies=[Depends(require_api_key)],
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        415: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
    summary="Find visually similar images",
    description=(
        "Accepts a base64-encoded JPEG or PNG image, embeds it via AWS Bedrock, "
        "runs an ANN search against the OpenSearch vector index, and returns the "
        "top-K most visually similar images with full metadata."
    ),
)
async def search_similar(raw_request: Request, body: SimilarSearchRequest) -> JSONResponse:
    request_id = str(uuid.uuid4())
    start_ms = time.monotonic() * 1000

    log_extra = {"request_id": request_id}
    logger.info(
        "Received /search/similar request top_k=%d project_id=%s",
        body.top_k,
        body.project_id,
        extra=log_extra,
    )

    # ------------------------------------------------------------------
    # 1. Decode base64 image
    # ------------------------------------------------------------------
    try:
        image_bytes = base64.b64decode(body.image, validate=True)
    except (binascii.Error, ValueError):
        return _error("INVALID_BASE64", "The 'image' field does not contain a valid Base64-encoded string.", 400)

    # ------------------------------------------------------------------
    # 2. Validate image size
    # ------------------------------------------------------------------
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return _error(
            "IMAGE_TOO_LARGE",
            f"Decoded image exceeds the maximum allowed size of {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            400,
        )

    # ------------------------------------------------------------------
    # 3. Validate image format (JPEG or PNG only)
    # ------------------------------------------------------------------
    fmt = _detect_image_format(image_bytes)
    if fmt is None:
        return _error(
            "UNSUPPORTED_FORMAT",
            "Only JPEG and PNG images are supported. Ensure the image is not corrupted.",
            400,
        )

    # ------------------------------------------------------------------
    # 4. Embed image via Bedrock
    # ------------------------------------------------------------------
    try:
        embedding = await embed_image(image_bytes, request_id)
    except EmbeddingError as exc:
        logger.error(
            "EmbeddingError %s: %s",
            exc.code,
            exc.message,
            extra=log_extra,
        )
        status = 504 if exc.code == "EMBEDDING_TIMEOUT" else 502
        return _error(exc.code, exc.message, status)

    # ------------------------------------------------------------------
    # 5. Run ANN search via shared search core (t9)
    # ------------------------------------------------------------------
    try:
        raw_results = await run_similarity_search(
            embedding=embedding,
            top_k=body.top_k,
            project_id=body.project_id,
            request_id=request_id,
        )
    except SearchCoreError as exc:
        logger.error("SearchCoreError: %s", exc, extra=log_extra)
        return _error("SEARCH_FAILED", f"Search core error: {exc}", 502)

    # ------------------------------------------------------------------
    # 6. Enrich results with metadata from OpenSearch
    # ------------------------------------------------------------------
    try:
        enriched = await enrich_results(raw_results, request_id)
    except Exception as exc:
        logger.error("Metadata enrichment error: %s", exc, extra=log_extra)
        return _error("SEARCH_FAILED", "Failed to retrieve image metadata.", 502)

    # ------------------------------------------------------------------
    # 7. Build and return response
    # ------------------------------------------------------------------
    query_time_ms = int(time.monotonic() * 1000 - start_ms)

    results = [ImageResult(**item) for item in enriched]

    logger.info(
        "Request completed http_status=200 results=%d query_time_ms=%d top_k=%d project_id=%s",
        len(results),
        query_time_ms,
        body.top_k,
        body.project_id,
        extra=log_extra,
    )

    return JSONResponse(
        status_code=200,
        content=SimilarSearchResponse(
            query_time_ms=query_time_ms,
            results=results,
        ).model_dump(),
    )
