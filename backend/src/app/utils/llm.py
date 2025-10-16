# backend/app/utils/llm.py
import json, requests

def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("` \n")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    return s

def llm_generate_json(system_prompt: str, user_prompt: str, model: str, endpoint: str, json_root: str):
    """
    Ruft Ollama /api/chat auf und erwartet reines JSON.
    Entfernt Code-Fences, prüft Struktur und gibt data[json_root] zurück.
    """
    url = endpoint.rstrip("/") + "/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role":"system","content": system_prompt},
            {"role":"user","content": user_prompt}
        ],
        "stream": False
    }
    r = requests.post(url, json=payload, timeout=120)
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "")
    content = _strip_fences(content)
    data = json.loads(content)
    if isinstance(data, dict) and json_root in data:
        return data[json_root]
    if isinstance(data, list):
        return data
    raise ValueError("Unexpected JSON shape from LLM")
