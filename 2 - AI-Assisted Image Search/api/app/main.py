"""
FastAPI application entry point — Visual Project Intelligence Search API.
"""

from __future__ import annotations

import logging
import sys

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models.schemas import ErrorResponse
from app.routes.search import router as search_router

# ---------------------------------------------------------------------------
# Logging — structured JSON-friendly format
# ---------------------------------------------------------------------------

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Visual Project Intelligence Search",
    description="AI-powered image similarity search for construction project photos.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Convert Pydantic / FastAPI validation errors into the standard error envelope.
    Maps field-level errors to the appropriate error codes.
    """
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = first.get("loc", ())
    field = loc[-1] if loc else "unknown"
    msg = first.get("msg", "Validation error")

    # Map field names to domain error codes
    code_map = {
        "image": "MISSING_FIELD",
        "top_k": "INVALID_TOP_K",
        "project_id": "INVALID_PROJECT_ID",
    }
    code = code_map.get(str(field), "VALIDATION_ERROR")

    # Distinguish missing vs invalid for the image field
    if field == "image" and "missing" in msg.lower():
        code = "MISSING_FIELD"
        msg = "The required field 'image' is missing from the request body."

    return JSONResponse(
        status_code=400,
        content=ErrorResponse(code=code, message=msg).model_dump(),
    )


@app.exception_handler(415)
async def unsupported_media_type_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=415,
        content=ErrorResponse(
            code="UNSUPPORTED_MEDIA_TYPE",
            message="Content-Type must be application/json.",
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(search_router, tags=["Search"])


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"status": "ok"}
