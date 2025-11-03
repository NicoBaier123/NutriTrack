#!/usr/bin/env python
"""
Lightweight embedding HTTP service for dbwdi RAG.

Usage:
    1. Install optional dependency: `pip install sentence-transformers fastapi uvicorn`
    2. Run the service: `uvicorn backend.scripts.embed_service:app --host 127.0.0.1 --port 8001`
    3. Ensure RAG_EMBED_URL points at http://127.0.0.1:8001/embed (default in config).

The Advisor router will POST {"texts": ["..."]} to /embed and expects
{"vectors": [[...]]} in response. This module keeps the interface stable
and can be swapped out for more advanced vector providers later.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer


class EmbedRequest(BaseModel):
    texts: List[str] = Field(default_factory=list, description="Texts to embed")


class EmbedResponse(BaseModel):
    vectors: List[List[float]]


@lru_cache(maxsize=1)
def _load_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> SentenceTransformer:
    # Cached model load so multiple requests reuse the same weights.
    return SentenceTransformer(model_name, device="cpu")


app = FastAPI(title="dbwdi Embedding Service", version="0.1")


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if not req.texts:
        raise HTTPException(status_code=400, detail="At least one text is required")

    model = _load_model()
    vectors = model.encode(req.texts, normalize_embeddings=True, convert_to_numpy=True)
    return EmbedResponse(vectors=vectors.tolist())


@app.get("/healthz")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.scripts.embed_service:app", host="127.0.0.1", port=8001, reload=False)
