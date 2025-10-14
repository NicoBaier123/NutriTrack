"""
Package alias: make `app` resolve to `backend.app`.

This lets commands like `uvicorn app.main:app` work from the repo root and
keeps existing absolute imports like `from app.db import ...` functional.
"""

from importlib import import_module
import sys as _sys

_backend_app = import_module("backend.app")

# Replace this package module with the real backend.app package object
_sys.modules[__name__] = _backend_app

