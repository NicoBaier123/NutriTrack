from __future__ import annotations

import http.client
import json
import os
import subprocess
from typing import Any, Dict, Optional

from fastapi import HTTPException

from .config import (
    LLAMA_CPP_MODEL_PATH,
    OLLAMA_HOST,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
)

SYSTEM_PROMPT_CHAT = (
    "Du bist ein hilfsbereiter, praeziser Ernährungs- und Fitnessassistent. "
    "Antworte knapp, klar und mit konkreten Zahlen, wenn sinnvoll. "
    "Wenn dir Informationen fehlen, nenne explizit, was du brauchst. "
    "Keine Halluzinationen: sei ehrlich, wenn du etwas nicht weißt."
)

LLAMA_CPP_AVAILABLE = False
try:  # pragma: no cover - optional dependency
    from llama_cpp import Llama  # type: ignore

    LLAMA_CPP_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    Llama = None  # type: ignore

_llama_cpp_handle: Optional["Llama"] = None


def build_chat_prompt(user_message: str, extra_context: Optional[str] = None) -> str:
    ctx = (extra_context or "").strip()
    if ctx:
        return (
            f"{SYSTEM_PROMPT_CHAT}\n\n[Kontext]\n{ctx}\n\n[Frage]\n{user_message}\n\n[Antwort]"
        )
    return f"{SYSTEM_PROMPT_CHAT}\n\n[Frage]\n{user_message}\n\n[Antwort]"


def _ollama_generate(
    prompt: str,
    model: str = OLLAMA_MODEL,
    as_json: bool = False,
    timeout: int = OLLAMA_TIMEOUT,
) -> str | Dict[str, Any]:
    conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
    body: Dict[str, Any] = {"model": model, "prompt": prompt, "stream": False}
    if as_json:
        body["format"] = "json"
        body["options"] = {"temperature": 0.3}
    conn.request(
        "POST",
        "/api/generate",
        body=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    res = conn.getresponse()
    if res.status != 200:
        raise HTTPException(status_code=503, detail=f"Ollama error {res.status}")
    outer = json.loads(res.read())
    text = outer.get("response", "")
    if as_json:
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "llm_invalid_json",
                    "hint": "Ollama lieferte kein valides JSON im Compose-Mode.",
                    "sample": text[:400],
                },
            ) from exc
    return text


def _ollama_alive(timeout: int = 2) -> bool:
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
        conn.request("GET", "/api/tags")
        res = conn.getresponse()
        return res.status == 200
    except Exception:
        return False


def _llm_generate(
    prompt: str,
    as_json: bool = False,
    temperature: float = 0.3,
    max_tokens: int = 512,
) -> str:
    if LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(
        LLAMA_CPP_MODEL_PATH
    ):
        global _llama_cpp_handle
        if _llama_cpp_handle is None:
            _llama_cpp_handle = Llama(  # type: ignore[call-arg]
                model_path=LLAMA_CPP_MODEL_PATH,
                n_ctx=8192,
                n_threads=os.cpu_count() or 4,
            )
        params = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        out = _llama_cpp_handle(**params)  # type: ignore[misc]
        text = out.get("choices", [{}])[0].get("text", "").strip()
        return text

    try:
        if as_json:
            conn = http.client.HTTPConnection(
                OLLAMA_HOST, OLLAMA_PORT, timeout=OLLAMA_TIMEOUT
            )
            body = json.dumps(
                {
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": temperature},
                }
            )
            conn.request(
                "POST",
                "/api/generate",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            res = conn.getresponse()
            if res.status == 200:
                data = json.loads(res.read())
                return data.get("response", "")
        else:
            return _ollama_generate(prompt, model=OLLAMA_MODEL, timeout=OLLAMA_TIMEOUT)
    except Exception:
        pass

    try:
        cmd = ["ollama", "run", OLLAMA_MODEL, prompt]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=max(OLLAMA_TIMEOUT, 120)
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    raise HTTPException(
        status_code=503,
        detail="Kein lokales LLM erreichbar (llama.cpp / Ollama).",
    )


def _parse_llm_json(raw: str) -> Dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise HTTPException(status_code=500, detail="KI-Ausgabe nicht parsebar.")
    return json.loads(raw[start : end + 1])

