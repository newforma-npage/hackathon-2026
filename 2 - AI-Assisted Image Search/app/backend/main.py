"""
Visual Project Intelligence Search — FastAPI backend.

Integrates:
  - AWS Rekognition  (label detection)
  - AWS Bedrock Titan Multimodal Embeddings  (image + text vectors)
  - Vector store  (OpenSearch k-NN or pgvector, configured via env vars)
  - photo-metadata.json  (source of truth for project / location metadata)
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import boto3
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import require_api_key

logger = logging.getLogger(__name__)

# JPEG magic: FF D8 FF  |  PNG magic: 89 50 4E 47 0D 0A 1A 0A
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC  = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

from .embeddings import BedrockEmbeddingClient, CURRENT_MODEL_VERSION
from .labeling import RekognitionLabeler
from .vector_store import (
    PhotoVector,
    SearchFilters,
    OpenSearchVectorStore,
    PgVectorStore,
    INDEX_EMBEDDING_DIM,
)

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent          # …/app
SAMPLE_DATA_DIR = BASE_DIR.parent / "Sample input data"
METADATA_FILE = SAMPLE_DATA_DIR / "photo-metadata.json"
FRONTEND_DIR = BASE_DIR / "frontend"

# ── AWS clients ───────────────────────────────────────────────────────────────
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
rekognition_labeler = RekognitionLabeler(region=AWS_REGION)
bedrock_client = BedrockEmbeddingClient(region=AWS_REGION)

# DynamoDB table written by the Lambda ingestion function.
# Optional — if not set, the app skips the ai_indexed flag update.
PHOTO_TABLE_NAME = os.getenv("PHOTO_TABLE_NAME")
_ddb_table = None


def get_ddb_table():
    """Lazy-init the DynamoDB table resource (only if PHOTO_TABLE_NAME is set)."""
    global _ddb_table
    if _ddb_table is None and PHOTO_TABLE_NAME:
        ddb = boto3.resource("dynamodb", region_name=AWS_REGION)
        _ddb_table = ddb.Table(PHOTO_TABLE_NAME)
    return _ddb_table


def mark_ai_indexed(project_id: str, image_path: str) -> None:
    """
    Flip ai_indexed=True on the DynamoDB record written by the Lambda.
    Silently skips if PHOTO_TABLE_NAME is not configured.
    """
    table = get_ddb_table()
    if table is None:
        return
    try:
        table.update_item(
            Key={"project_id": project_id, "image_path": image_path},
            UpdateExpression="SET ai_indexed = :val",
            ExpressionAttributeValues={":val": True},
        )
    except Exception as exc:
        # Non-fatal — log and continue; the vector store is the source of truth
        import logging
        logging.getLogger(__name__).warning("Could not update ai_indexed in DynamoDB: %s", exc)

# ── Vector store (lazy init) ──────────────────────────────────────────────────
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "opensearch").lower()  # "opensearch" | "pgvector"

_vector_store: Optional[OpenSearchVectorStore | PgVectorStore] = None


def get_vector_store() -> OpenSearchVectorStore | PgVectorStore:
    global _vector_store
    if _vector_store is None:
        if VECTOR_BACKEND == "pgvector":
            _vector_store = PgVectorStore()
        else:
            _vector_store = OpenSearchVectorStore()
    return _vector_store


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Visual Project Intelligence Search", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ── Metadata helpers ──────────────────────────────────────────────────────────

def load_metadata() -> dict:
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


def save_metadata(data: dict) -> None:
    with open(METADATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_image_path(filename: str) -> Path:
    return SAMPLE_DATA_DIR / filename


def find_photo(data: dict, filename: str) -> Optional[dict]:
    for p in data["photos"]:
        if p["filename"] == filename:
            return p
    return None


# ── Ingestion helper ──────────────────────────────────────────────────────────

def _ingest_photo(photo: dict, image_bytes: bytes) -> PhotoVector:
    """
    Run Rekognition labeling + Bedrock embedding on image_bytes.
    Updates the photo dict in-place and returns a PhotoVector for the vector store.
    Raises if the image is flagged for moderation.
    """
    # 1. Rekognition — labels + moderation check (concurrent internally)
    labeling = rekognition_labeler.label(image_bytes)

    if labeling.is_flagged:
        raise ValueError(
            f"Image flagged for moderation: {', '.join(labeling.moderation_flags)}"
        )

    # 2. Bedrock multimodal embedding (image)
    embedding = bedrock_client.embed_image(image_bytes)

    # 3. Update in-memory metadata record with full tag schema
    photo.update(labeling.to_metadata_patch())
    photo["index_version"] = CURRENT_MODEL_VERSION
    photo["indexed_at"] = datetime.utcnow().isoformat()

    # 4. Build PhotoVector for the vector store
    date_taken: Optional[datetime] = None
    if photo.get("date_taken"):
        try:
            date_taken = datetime.fromisoformat(photo["date_taken"])
        except ValueError:
            pass

    photo_id = photo.get("photo_id") or str(uuid.uuid5(uuid.NAMESPACE_URL, photo["filename"]))
    photo["photo_id"] = photo_id

    return PhotoVector(
        photo_id=photo_id,
        embedding=embedding,
        project_id=photo.get("project_id", ""),
        project_name=photo.get("project_name", ""),
        filename=photo["filename"],
        date_taken=date_taken,
        location=photo.get("location"),
        taken_by=photo.get("taken_by"),
        ai_labels=labeling.ai_labels,
        ai_description=labeling.description,
        index_version=CURRENT_MODEL_VERSION,
        indexed_at=datetime.utcnow(),
    )


# ── Pydantic models ───────────────────────────────────────────────────────────

class TextSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    project_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    detected_labels: Optional[list[str]] = None
    page: int = Field(default=0, ge=0)
    page_size: int = Field(default=20, ge=1, le=50)


class SimilarImageRequest(BaseModel):
    """Request body for POST /search/similar (P5)."""
    image: str = Field(..., description="Base64-encoded JPEG or PNG image.")
    top_k: int = Field(default=10, ge=1, le=50, description="Max results to return (1–50).")
    project_id: Optional[str] = Field(default=None, min_length=1, max_length=256)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Visual Project Intelligence Search API v2", "docs": "/docs"}


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    path = FRONTEND_DIR / "favicon.svg"
    if path.exists():
        return FileResponse(str(path), media_type="image/svg+xml")
    return JSONResponse(status_code=404, content={"detail": "Not found"})


@app.get("/api/photos")
def list_photos():
    """Return all photos with their metadata."""
    return load_metadata()["photos"]


@app.get("/api/photos/{filename}/image")
def get_image(filename: str):
    path = get_image_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(path), media_type="image/jpeg")


@app.get("/api/projects")
def list_projects():
    data = load_metadata()
    seen: dict[str, str] = {}
    for p in data["photos"]:
        pid = p.get("project_id")
        if pid and pid not in seen:
            seen[pid] = p.get("project_name", pid)
    return [{"project_id": k, "project_name": v} for k, v in seen.items()]


@app.post("/api/photos/{filename}/ingest", dependencies=[Depends(require_api_key)])
def ingest_photo(filename: str):
    """
    Run Rekognition + Bedrock on a single photo, store labels in metadata,
    and upsert the embedding vector into the vector store.
    """
    path = get_image_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    data = load_metadata()
    photo = find_photo(data, filename)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found in metadata")

    try:
        image_bytes = path.read_bytes()
        pv = _ingest_photo(photo, image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion error: {exc}")

    try:
        get_vector_store().upsert(pv)
    except Exception as exc:
        # Vector store unavailable — still save metadata, surface warning
        save_metadata(data)
        return {
            "filename": filename,
            "photo_id": pv.photo_id,
            "ai_labels": pv.ai_labels,
            "ai_description": pv.ai_description,
            "warning": f"Metadata saved but vector store upsert failed: {exc}",
        }

    save_metadata(data)
    # Flip ai_indexed flag in DynamoDB (written by the Lambda ingestion function)
    project_id = photo.get("project_id", "")
    image_path = f"{project_id}/{filename}" if project_id else filename
    mark_ai_indexed(project_id, image_path)
    return {
        "filename": filename,
        "photo_id": pv.photo_id,
        "ai_labels": pv.ai_labels,
        "ai_description": pv.ai_description,
        "embedding_dim": len(pv.embedding),
        "status": "indexed",
    }


@app.post("/api/photos/ingest-all", dependencies=[Depends(require_api_key)])
def ingest_all_photos():
    """
    Ingest every photo that has not yet been indexed (no ai_labels).
    Runs Rekognition + Bedrock and upserts into the vector store.
    """
    data = load_metadata()
    results = []

    for photo in data["photos"]:
        if photo.get("ai_labels"):
            results.append({"filename": photo["filename"], "status": "skipped (already indexed)"})
            continue

        path = get_image_path(photo["filename"])
        if not path.exists():
            results.append({"filename": photo["filename"], "status": "skipped (file not found)"})
            continue

        try:
            image_bytes = path.read_bytes()
            pv = _ingest_photo(photo, image_bytes)
            get_vector_store().upsert(pv)
            # Flip ai_indexed in DynamoDB
            pid = photo.get("project_id", "")
            mark_ai_indexed(pid, f"{pid}/{photo['filename']}" if pid else photo["filename"])
            results.append({
                "filename": photo["filename"],
                "photo_id": pv.photo_id,
                "status": "indexed",
                "labels": pv.ai_labels[:5],
            })
        except Exception as exc:
            results.append({"filename": photo["filename"], "status": f"error: {exc}"})

    save_metadata(data)
    indexed = sum(1 for r in results if r["status"] == "indexed")
    return {"processed": len(results), "indexed": indexed, "results": results}


@app.post("/api/search", dependencies=[Depends(require_api_key)])
def search_photos(req: TextSearchRequest):
    """
    Natural-language semantic search using Bedrock text embeddings + vector kNN.
    Falls back to label/metadata keyword scoring if the vector store is unavailable.
    """
    # Build filters
    filters = SearchFilters(
        project_ids=[req.project_id] if req.project_id else None,
        detected_labels=req.detected_labels,
    )
    if req.date_from:
        try:
            filters.date_from = datetime.fromisoformat(req.date_from)
        except ValueError:
            pass
    if req.date_to:
        try:
            filters.date_to = datetime.fromisoformat(req.date_to)
        except ValueError:
            pass

    # Attempt vector search
    try:
        query_vector = bedrock_client.embed_text(req.query)
        candidates = get_vector_store().knn_search(query_vector, k=50, filters=filters)

        # Map photo_id → score
        score_map = {c.photo_id: c.score for c in candidates}

        data = load_metadata()
        photos = [p for p in data["photos"] if p.get("photo_id") in score_map]
        photos.sort(key=lambda p: score_map[p["photo_id"]], reverse=True)

        # Attach score to each result
        for p in photos:
            p["_score"] = round(score_map[p["photo_id"]], 4)

        # Paginate
        start = req.page * req.page_size
        page = photos[start: start + req.page_size]

        return {
            "query": req.query,
            "mode": "vector",
            "total": len(photos),
            "page": req.page,
            "page_size": req.page_size,
            "results": page,
        }

    except Exception as exc:
        # Graceful degradation: keyword fallback
        data = load_metadata()
        photos = data["photos"]

        if req.project_id:
            photos = [p for p in photos if p.get("project_id") == req.project_id]

        terms = req.query.lower().split()

        def _score(photo: dict) -> int:
            # Build a comprehensive searchable blob from all metadata fields
            tag_names = []
            for tag in (photo.get("ai_tags") or []):
                tag_names.append(tag.get("name", "").lower())
                tag_names.append(tag.get("category", "").lower())
                tag_names.extend(p.lower() for p in tag.get("parents", []))

            blob = " ".join([
                photo.get("ai_description") or "",
                " ".join(photo.get("ai_labels") or []),
                " ".join(tag_names),
                photo.get("location", ""),
                photo.get("project_name", ""),
                photo.get("filename", ""),
                photo.get("taken_by", ""),
            ]).lower()
            return sum(1 for t in terms if t in blob)

        scored = [(s, p) for p in photos if (s := _score(p)) > 0]
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [p for _, p in scored]

        start = req.page * req.page_size
        page = results[start: start + req.page_size]

        return {
            "query": req.query,
            "mode": "keyword_fallback",
            "fallback_reason": str(exc),
            "total": len(results),
            "page": req.page,
            "page_size": req.page_size,
            "results": page,
        }


@app.post("/api/search/similarity", dependencies=[Depends(require_api_key)])
async def similarity_search(file: UploadFile = File(...)):
    """
    Upload an image → embed with Bedrock Titan Multimodal → kNN search.
    Falls back to Rekognition label overlap if vector store is unavailable.
    """
    image_bytes = await file.read()

    try:
        query_vector = bedrock_client.embed_image(image_bytes)
        candidates = get_vector_store().knn_search(query_vector, k=50)

        score_map = {c.photo_id: c.score for c in candidates}
        data = load_metadata()
        photos = [p for p in data["photos"] if p.get("photo_id") in score_map]
        photos.sort(key=lambda p: score_map[p["photo_id"]], reverse=True)
        for p in photos:
            p["_score"] = round(score_map[p["photo_id"]], 4)

        return {
            "mode": "vector",
            "embedding_dim": len(query_vector),
            "total": len(photos),
            "results": photos,
        }

    except Exception as exc:
        # Fallback: Rekognition label overlap
        try:
            fallback_result = rekognition_labeler.label(image_bytes)
            upload_labels = set(fallback_result.ai_labels)
        except Exception as rek_exc:
            raise HTTPException(status_code=500, detail=f"Both vector and Rekognition failed: {rek_exc}")

        data = load_metadata()
        scored = []
        for photo in data["photos"]:
            photo_labels = set(photo.get("ai_labels") or [])
            overlap = len(upload_labels & photo_labels)
            if overlap > 0:
                scored.append((overlap, photo))
        scored.sort(key=lambda x: x[0], reverse=True)

        return {
            "mode": "label_overlap_fallback",
            "fallback_reason": str(exc),
            "upload_labels": list(upload_labels),
            "total": len(scored),
            "results": [p for _, p in scored],
        }


@app.post("/api/vector-store/init", dependencies=[Depends(require_api_key)])
def init_vector_store():
    """Create the vector index / table if it does not exist."""
    try:
        vs = get_vector_store()
        if isinstance(vs, OpenSearchVectorStore):
            vs.create_index()
        elif isinstance(vs, PgVectorStore):
            vs.create_table()
        return {"status": "ok", "backend": VECTOR_BACKEND}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── P5: POST /search/similar ──────────────────────────────────────────────────

def _detect_image_format(data: bytes) -> Optional[str]:
    """Return 'jpeg', 'png', or None if the format is not recognised."""
    if data[:3] == _JPEG_MAGIC:
        return "jpeg"
    if data[:8] == _PNG_MAGIC:
        return "png"
    return None


def _error_json(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message})


@app.post("/search/similar", dependencies=[Depends(require_api_key)])
def search_similar(req: SimilarImageRequest):
    """
    P5 — Similarity search endpoint.

    Accepts a base64-encoded JPEG or PNG image, embeds it via
    Bedrock Titan Multimodal (same model used at ingest time),
    runs a kNN search against the vector store, and returns the
    top-K most visually similar images with full metadata.

    Request body:
        image      (str, required)  Base64-encoded JPEG or PNG.
        top_k      (int, optional)  1–50, default 10.
        project_id (str, optional)  Restrict results to one project.

    Returns HTTP 200 with:
        query_time_ms  int
        results        list of enriched photo dicts with similarity_score
    """
    request_id = str(uuid.uuid4())
    start_ms = time.monotonic() * 1000

    # 1. Decode base64
    try:
        image_bytes = base64.b64decode(req.image, validate=True)
    except (binascii.Error, ValueError):
        return _error_json(
            "INVALID_BASE64",
            "The 'image' field does not contain a valid Base64-encoded string.",
            400,
        )

    # 2. Size check
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return _error_json(
            "IMAGE_TOO_LARGE",
            f"Decoded image exceeds the maximum allowed size of {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            400,
        )

    # 3. Format check (JPEG or PNG only)
    if _detect_image_format(image_bytes) is None:
        return _error_json(
            "UNSUPPORTED_FORMAT",
            "Only JPEG and PNG images are supported.",
            400,
        )

    # 4. Embed via Bedrock (reuse existing BedrockEmbeddingClient)
    try:
        query_vector = bedrock_client.embed_image(image_bytes)
    except Exception as exc:
        logger.error("[%s] Bedrock embedding failed: %s", request_id, exc)
        return _error_json("EMBEDDING_FAILED", f"Image embedding failed: {exc}", 502)

    # 5. kNN search via vector store (reuse existing OpenSearchVectorStore)
    filters = SearchFilters(
        project_ids=[req.project_id] if req.project_id else None,
    )
    try:
        candidates = get_vector_store().knn_search(query_vector, k=req.top_k, filters=filters)
    except Exception as exc:
        logger.error("[%s] Vector search failed: %s", request_id, exc)
        return _error_json("SEARCH_FAILED", f"Search failed: {exc}", 502)

    # 6. Enrich results with metadata from photo-metadata.json
    score_map = {c.photo_id: c.score for c in candidates}
    data = load_metadata()

    results = []
    for photo in data["photos"]:
        pid = photo.get("photo_id")
        if pid and pid in score_map:
            enriched = dict(photo)
            enriched["similarity_score"] = round(score_map[pid], 4)
            results.append(enriched)

    # Sort by similarity descending
    results.sort(key=lambda p: p["similarity_score"], reverse=True)

    query_time_ms = int(time.monotonic() * 1000 - start_ms)

    logger.info(
        "[%s] /search/similar completed results=%d query_time_ms=%d top_k=%d project_id=%s",
        request_id, len(results), query_time_ms, req.top_k, req.project_id,
    )

    return JSONResponse(
        status_code=200,
        content={"query_time_ms": query_time_ms, "results": results},
    )
