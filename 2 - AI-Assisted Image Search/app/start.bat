@echo off
echo Starting Visual Project Intelligence Search...
echo.

cd /d "%~dp0backend"

echo Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo Starting backend server on http://localhost:8000
echo Open frontend\index.html in your browser
echo.
echo Press Ctrl+C to stop
echo.

python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
