from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from ..config import LLAMA_CPP_MODEL_PATH
from ..llm import LLAMA_CPP_AVAILABLE, _llm_generate, build_chat_prompt
from ..schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def advisor_chat(payload: ChatRequest):
    prompt = build_chat_prompt(payload.message, payload.context)
    try:
        text = _llm_generate(prompt, as_json=payload.json_mode)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"LLM-Fehler: {exc!s}")

    backend = "ollama_http"
    if LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(LLAMA_CPP_MODEL_PATH):
        backend = "llama_cpp"

    return ChatResponse(output=text, used_backend=backend)

