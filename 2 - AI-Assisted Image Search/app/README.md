# Visual Project Intelligence Search

AI-powered image search for construction project photos, using AWS Rekognition for automatic tagging and natural language search.

## Features

| Feature | Description |
|---|---|
| **Natural Language Search** | Search with plain English: "bridge", "concrete crack", "steel beam" |
| **Auto-Tagging** | AWS Rekognition detects and labels objects in every photo |
| **Similarity Search** | Upload a photo to find visually similar images across all projects |
| **Smart Filters** | Filter results by project, date range |
| **Project Context** | Every image links back to its project, location, and metadata |

## Prerequisites

- Python 3.11+
- AWS credentials configured (`aws configure` or environment variables)
- AWS Rekognition access in your region

## Setup & Run

```bash
# 1. Install dependencies
cd "2 - AI-Assisted Image Search/app"
pip install -r requirements.txt

# 2. (Optional) Set AWS region
set AWS_REGION=us-east-1

# 3. Start the server
uvicorn backend.main:app --reload --port 8000
```

Then open **http://localhost:8000** in your browser.

## Usage

### Auto-Tag Images
Click **✨ Auto-Tag All Images** in the top-right. This runs AWS Rekognition on every untagged photo and stores the labels back into `photo-metadata.json`.

### Text Search
Type a natural language query (e.g. `foundation crack`) and press **Search**. Optionally filter by project or date range.

### Similarity Search
Switch to the **Similarity Search** tab, upload any image, and click **Find Similar Images**. The app compares Rekognition labels from your upload against all indexed photos.

## Architecture

```
app/
├── backend/
│   └── main.py          # FastAPI app — Rekognition, search, metadata CRUD
├── frontend/
│   └── index.html       # Single-page UI (vanilla JS, no build step)
└── requirements.txt
```

The backend reads/writes `../Sample input data/photo-metadata.json` and serves images directly from `../Sample input data/`.

## AWS Services Used

- **Amazon Rekognition** — `DetectLabels` for automatic image tagging and similarity matching
