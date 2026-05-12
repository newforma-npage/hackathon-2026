"""
Visual Project Intelligence Search - Backend API
FastAPI server that uses AWS Rekognition for image tagging and natural language search.
"""

import json
import os
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional

import boto3
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_DATA_DIR = BASE_DIR.parent / "Sample input data"
METADATA_FILE = SAMPLE_DATA_DIR / "photo-metadata.json"

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

# ── AWS clients ───────────────────────────────────────────────────────────────
rekognition = boto3.client("rekognition", region_name=AWS_REGION)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Visual Project Intelligence Search", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static frontend
frontend_dir = BASE_DIR / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ── Data helpers ──────────────────────────────────────────────────────────────
def load_metadata() -> dict:
    with open(METADATA_FILE, "r") as f:
        return json.load(f)


def save_metadata(data: dict) -> None:
    with open(METADATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_image_path(filename: str) -> Path:
    return SAMPLE_DATA_DIR / filename


# ── Rekognition helpers ───────────────────────────────────────────────────────
def detect_labels_from_file(image_path: Path) -> tuple[list[str], str]:
    """Run Rekognition DetectLabels on a local image file. Returns (labels, description)."""
    with open(image_path, "rb") as img_file:
        image_bytes = img_file.read()

    response = rekognition.detect_labels(
        Image={"Bytes": image_bytes},
        MaxLabels=20,
        MinConfidence=70,
    )

    labels = [label["Name"].lower() for label in response["Labels"]]
    description = ", ".join(label["Name"] for label in response["Labels"][:8])
    return labels, description


def detect_labels_from_bytes(image_bytes: bytes) -> tuple[list[str], str]:
    """Run Rekognition DetectLabels on raw bytes. Returns (labels, description)."""
    response = rekognition.detect_labels(
        Image={"Bytes": image_bytes},
        MaxLabels=20,
        MinConfidence=70,
    )
    labels = [label["Name"].lower() for label in response["Labels"]]
    description = ", ".join(label["Name"] for label in response["Labels"][:8])
    return labels, description


def score_photo(photo: dict, query_terms: list[str]) -> int:
    """Return a relevance score for a photo given a list of query terms."""
    score = 0
    searchable = " ".join(
        [
            photo.get("ai_description") or "",
            " ".join(photo.get("ai_labels") or []),
            " ".join(photo.get("tags") or []),
            photo.get("location", ""),
            photo.get("project_name", ""),
        ]
    ).lower()

    for term in query_terms:
        if term in searchable:
            score += 1
    return score


# ── Models ────────────────────────────────────────────────────────────────────
class SearchRequest(BaseModel):
    query: str
    project_id: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    index = frontend_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"message": "Visual Project Intelligence Search API", "docs": "/docs"}


@app.get("/api/photos")
def list_photos():
    """Return all photos with their metadata."""
    data = load_metadata()
    return data["photos"]


@app.get("/api/photos/{filename}/image")
def get_image(filename: str):
    """Serve a photo file."""
    path = get_image_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(path), media_type="image/jpeg")


@app.post("/api/photos/{filename}/tag")
def tag_photo(filename: str):
    """
    Run AWS Rekognition on a single photo and store the resulting labels
    back into the metadata file.
    """
    path = get_image_path(filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    try:
        labels, description = detect_labels_from_file(path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rekognition error: {exc}")

    data = load_metadata()
    for photo in data["photos"]:
        if photo["filename"] == filename:
            photo["ai_labels"] = labels
            photo["ai_description"] = description
            break
    else:
        raise HTTPException(status_code=404, detail="Photo not found in metadata")

    save_metadata(data)
    return {"filename": filename, "ai_labels": labels, "ai_description": description}


@app.post("/api/photos/tag-all")
def tag_all_photos():
    """
    Run AWS Rekognition on every photo that has not yet been tagged.
    Returns a summary of what was processed.
    """
    data = load_metadata()
    results = []

    for photo in data["photos"]:
        if photo.get("ai_labels"):
            results.append({"filename": photo["filename"], "status": "skipped (already tagged)"})
            continue

        path = get_image_path(photo["filename"])
        if not path.exists():
            results.append({"filename": photo["filename"], "status": "skipped (file not found)"})
            continue

        try:
            labels, description = detect_labels_from_file(path)
            photo["ai_labels"] = labels
            photo["ai_description"] = description
            results.append({"filename": photo["filename"], "status": "tagged", "labels": labels})
        except Exception as exc:
            results.append({"filename": photo["filename"], "status": f"error: {exc}"})

    save_metadata(data)
    return {"processed": len(results), "results": results}


@app.post("/api/search")
def search_photos(req: SearchRequest):
    """
    Natural-language search across all tagged photos.
    Optionally filter by project_id and date range.
    """
    data = load_metadata()
    photos = data["photos"]

    # Apply project filter
    if req.project_id:
        photos = [p for p in photos if p.get("project_id") == req.project_id]

    # Apply date filters
    if req.date_from:
        try:
            df = datetime.fromisoformat(req.date_from)
            photos = [p for p in photos if datetime.fromisoformat(p["date_taken"]) >= df]
        except ValueError:
            pass

    if req.date_to:
        try:
            dt = datetime.fromisoformat(req.date_to)
            photos = [p for p in photos if datetime.fromisoformat(p["date_taken"]) <= dt]
        except ValueError:
            pass

    # Score by query terms
    query_terms = req.query.lower().split()
    scored = [(score_photo(p, query_terms), p) for p in photos]
    scored = [(s, p) for s, p in scored if s > 0]
    scored.sort(key=lambda x: x[0], reverse=True)

    return {
        "query": req.query,
        "total": len(scored),
        "results": [p for _, p in scored],
    }


@app.post("/api/search/similarity")
async def similarity_search(file: UploadFile = File(...)):
    """
    Upload an image and find visually similar photos using Rekognition labels.
    """
    image_bytes = await file.read()

    try:
        upload_labels, _ = detect_labels_from_bytes(image_bytes)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Rekognition error: {exc}")

    data = load_metadata()
    scored = []
    for photo in data["photos"]:
        photo_labels = set(photo.get("ai_labels") or [])
        if not photo_labels:
            continue
        overlap = len(set(upload_labels) & photo_labels)
        if overlap > 0:
            scored.append((overlap, photo))

    scored.sort(key=lambda x: x[0], reverse=True)

    return {
        "upload_labels": upload_labels,
        "total": len(scored),
        "results": [p for _, p in scored],
    }


@app.get("/api/projects")
def list_projects():
    """Return distinct projects from the metadata."""
    data = load_metadata()
    seen = {}
    for photo in data["photos"]:
        pid = photo.get("project_id")
        if pid and pid not in seen:
            seen[pid] = photo.get("project_name", pid)
    return [{"project_id": k, "project_name": v} for k, v in seen.items()]
