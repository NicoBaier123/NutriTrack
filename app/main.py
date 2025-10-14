"""
Forwarder module to support `uvicorn app.main:app` from repo root.

The actual FastAPI application lives in `backend.app.main`. Import and re-export it here.
"""

from backend.app.main import app  # re-export

__all__ = ["app"]
