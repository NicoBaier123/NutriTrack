"""
Convenience re-export so the embedding service can be launched via
`uvicorn backend.embed_service:app`.

This keeps legacy `backend/src` layout untouched while providing a stable
import path for uvicorn.
"""

from __future__ import annotations

from backend.scripts.embed_service import app  # noqa: F401
