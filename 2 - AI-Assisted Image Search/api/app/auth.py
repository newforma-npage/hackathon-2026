"""
API key authentication dependency for FastAPI.

Usage
-----
Add `_: None = Depends(require_api_key)` to any route that needs auth.

Configuration
-------------
Set the API_KEY environment variable to a secret string.
If API_KEY is not set (e.g. local dev), auth is DISABLED and a warning is logged.

Clients must send the key in the X-API-Key header:
    X-API-Key: <your-secret-key>
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

logger = logging.getLogger(__name__)

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

_CONFIGURED_KEY: str | None = os.getenv("API_KEY")

if not _CONFIGURED_KEY:
    logger.warning(
        "API_KEY environment variable is not set — authentication is DISABLED. "
        "Set API_KEY to a secret value before deploying to production."
    )


def require_api_key(key: str | None = Security(_API_KEY_HEADER)) -> None:
    """
    FastAPI dependency that enforces API key authentication.

    Raises HTTP 401 if the key is missing.
    Raises HTTP 403 if the key is present but incorrect.
    Passes silently if API_KEY env var is not configured (dev mode).
    """
    if not _CONFIGURED_KEY:
        return

    if key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide it in the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not secrets.compare_digest(key, _CONFIGURED_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
