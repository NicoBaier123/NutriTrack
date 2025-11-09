from __future__ import annotations

import os

from app.core.config import get_settings

SETTINGS = get_settings()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "100"))

RAG_EMBED_URL = os.getenv("RAG_EMBED_URL")
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "30"))
RAG_MAX_RECIPES = int(os.getenv("RAG_MAX_RECIPES", "0"))

LLAMA_CPP_MODEL_PATH = os.getenv("LLAMA_CPP_MODEL_PATH")

try:
    from app.models.recipes import Recipe, RecipeItem  # noqa: F401

    HAS_RECIPES = True
except Exception:  # pragma: no cover - optional dependency
    HAS_RECIPES = False
    Recipe = None  # type: ignore
    RecipeItem = None  # type: ignore

