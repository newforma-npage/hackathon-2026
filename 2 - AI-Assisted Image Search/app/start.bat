@echo off
echo Starting Visual Project Intelligence Search...
echo.

cd /d "%~dp0"

REM Load .env file if it exists
if exist .env (
    echo Loading environment from .env...
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if not "%%A"=="" if not "%%A:~0,1%"=="#" (
            set "%%A=%%B"
        )
    )
)

cd backend

echo Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo Starting backend server on http://localhost:8000
echo Open http://localhost:8000 in your browser
echo.
echo Press Ctrl+C to stop
echo.

python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
