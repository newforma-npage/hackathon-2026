# Visual Project Intelligence Search

AI-powered image search for construction site photos using AWS Rekognition.

## Quick Start

### 1. Start the backend
```
cd app
start.bat
```
Or manually:
```
cd app/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 2. Open the frontend
Open `app/frontend/index.html` in your browser.

## Features
- **Natural language search** — search by content, location, project
- **AI analysis** — click "Analyze All with AI" to run AWS Rekognition on all 16 photos
- **Smart filters** — filter by project or photographer
- **Photo detail** — click any photo to see full metadata, AI labels with confidence scores
- **Suggestion chips** — quick searches for common construction terms

## Architecture
- **Frontend**: Vanilla HTML/CSS/JS — Newforma brand styled
- **Backend**: FastAPI (Python) + boto3
- **AI**: AWS Rekognition (detect_labels)
- **Data**: photo-metadata.json enriched with AI results saved to enriched-metadata.json
