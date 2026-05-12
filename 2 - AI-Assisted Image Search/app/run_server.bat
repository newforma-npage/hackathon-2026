@echo off
cd /d "%~dp0"

REM Load .env file
for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
    if not "%%A"=="" set "%%A=%%B"
)

echo.
echo ============================================
echo  Visual Project Intelligence Search
echo  http://localhost:8000
echo ============================================
echo.

uv run --python 3.12 --with fastapi==0.115.0 --with uvicorn --with boto3==1.35.0 --with python-multipart --with pydantic uvicorn backend.main:app --host 0.0.0.0 --port 8000
