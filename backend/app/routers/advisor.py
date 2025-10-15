# backend/app/routers/advisor.py
from __future__ import annotations
from datetime import date
from typing import List, Optional, Literal, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select
import http.client, json, os, math
import subprocess
from typing import Tuple
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse


from app.db import get_session
from app.models.foods import Food
from app.models.meals import Meal, MealItem
from app.routers.summary import _intake_for_day, _active_minutes_for_day, _target_kcal_for_day

# --- Optional: Rezepte, falls vorhanden (sonst stiller Fallback auf Foods) ---
try:
    from app.models.recipes import Recipe, RecipeItem
    HAS_RECIPES = True
except Exception:
    HAS_RECIPES = False

router = APIRouter(prefix="/advisor", tags=["advisor"])

# ==================== Modelle ====================

class MacroTotals(BaseModel):
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0

class GapsResponse(BaseModel):
    day: date
    target: Optional[MacroTotals] = None
    intake: MacroTotals
    remaining: Optional[MacroTotals] = None
    notes: List[str] = []

class SuggestionItem(BaseModel):
    food: str
    grams: float

class Suggestion(BaseModel):
    name: str
    items: List[SuggestionItem]
    source: Literal["db", "llm", "cookbook", "rag"] = "db"
    est_kcal: Optional[float] = None
    est_protein_g: Optional[float] = None
    est_carbs_g: Optional[float] = None
    est_fat_g: Optional[float] = None

class RecommendationsResponse(BaseModel):
    day: date
    remaining: MacroTotals
    mode: Literal["db", "open", "rag", "hybrid"]
    suggestions: List[Suggestion]

class Prefs(BaseModel):
    veggie: Optional[bool] = None
    vegan: Optional[bool] = None
    no_pork: Optional[bool] = None
    lactose_free: Optional[bool] = None
    gluten_free: Optional[bool] = None
    allergens_avoid: Optional[List[str]] = None
    budget_level: Optional[Literal["low","mid","high"]] = None
    cuisine_bias: Optional[List[str]] = None  # ["de", "med", "asian", ...]

# ==================== ENV / KI / RAG ====================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
# Kurzzeit-Timeouts, damit die UI schnell reagiert, wenn kein LLM läuft
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "10"))

RAG_EMBED_URL = os.getenv("RAG_EMBED_URL")  # z.B. http://127.0.0.1:8001/embed
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "30"))

# NEU: Optionaler In-Process LLM (llama-cpp), sonst Fallback auf Ollama HTTP oder CLI.
LLAMA_CPP_AVAILABLE = False
try:
    # Wird nur genutzt, wenn Paket installiert ist (pip install llama-cpp-python)
    from llama_cpp import Llama  # type: ignore
    LLAMA_CPP_AVAILABLE = True
except Exception:
    pass

# ENV für In-Process-Modell (ggf. anpassen, z.B. gguf Datei)
LLAMA_CPP_MODEL_PATH = os.getenv("LLAMA_CPP_MODEL_PATH")  # z.B. "/models/llama3.1.Q4_K_M.gguf"

_llama_cpp_handle = None  # lazy init

def _llm_generate(
    prompt: str,
    as_json: bool = False,
    temperature: float = 0.3,
    max_tokens: int = 512,
) -> str:
    """
    Universeller LLM-Adapter:
    1) llama.cpp in-process (falls installiert & MODEL_PATH vorhanden)
    2) Ollama HTTP (deine existierende _ollama_generate)
    3) Ollama CLI (subprocess)
    """
    # 1) In-Process llama.cpp
    if LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(LLAMA_CPP_MODEL_PATH):
        global _llama_cpp_handle
        if _llama_cpp_handle is None:
            _llama_cpp_handle = Llama(model_path=LLAMA_CPP_MODEL_PATH, n_ctx=8192, n_threads=os.cpu_count() or 4)
        # Einfacher Prompt; für Chat-Formate ggf. Nachrichtenstruktur bauen
        params = {
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        out = _llama_cpp_handle(**params)
        text = out.get("choices", [{}])[0].get("text", "").strip()
        return text

    # 2) Ollama HTTP (nutzt deine vorhandene _ollama_generate)
    try:
        if as_json:
            # JSON-Modus via /api/generate mit format=json erzwingen
            conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=OLLAMA_TIMEOUT)
            body = json.dumps({
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature},
            })
            conn.request("POST", "/api/generate", body=body, headers={"Content-Type": "application/json"})
            res = conn.getresponse()
            if res.status == 200:
                data = json.loads(res.read())
                return data.get("response", "")
        else:
            return _ollama_generate(prompt, model=OLLAMA_MODEL, timeout=OLLAMA_TIMEOUT)
    except Exception:
        pass

    # 3) Ollama CLI (fallback, benötigt installierte ollama CLI)
    try:
        cmd = ["ollama", "run", OLLAMA_MODEL, prompt]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    raise HTTPException(status_code=503, detail="Kein lokales LLM erreichbar (llama.cpp / Ollama).")

# NEU: System-Prompt für Chat-ähnliche Antworten (de, sachlich, knapp, hilfreich).
SYSTEM_PROMPT_CHAT = (
    "Du bist ein hilfsbereiter, präziser Ernährungs- und Fitnessassistent. "
    "Antworte knapp, klar und mit konkreten Zahlen, wenn sinnvoll. "
    "Wenn dir Informationen fehlen, nenne explizit, was du brauchst. "
    "Keine Halluzinationen: sei ehrlich, wenn du etwas nicht weißt."
)

def build_chat_prompt(user_message: str, extra_context: Optional[str] = None) -> str:
    ctx = (extra_context or "").strip()
    if ctx:
        return f"{SYSTEM_PROMPT_CHAT}\n\n[Kontext]\n{ctx}\n\n[Frage]\n{user_message}\n\n[Antwort]"
    return f"{SYSTEM_PROMPT_CHAT}\n\n[Frage]\n{user_message}\n\n[Antwort]"


def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL, as_json: bool = False, timeout=60) -> str:
    conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
    body = {"model": model, "prompt": prompt, "stream": False}
    if as_json:
        body["format"] = "json"
        body["options"] = {"temperature": 0.3}
    conn.request("POST", "/api/generate", body=json.dumps(body), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    if res.status != 200:
        raise HTTPException(status_code=503, detail=f"Ollama error {res.status}")
    data = json.loads(res.read())
    return data.get("response", "")


def _ollama_alive(timeout: int = 2) -> bool:
    """Schneller Reachability-Check für Ollama HTTP API."""
    try:
        conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
        conn.request("GET", "/api/tags")
        res = conn.getresponse()
        return res.status == 200
    except Exception:
        return False


def _post_meal_ingest(items, day_str, input_text):
    """
    items: List[{"name": str, "grams": float}]  # was dein Parser/LLM liefert
    day_str: "YYYY-MM-DD"
    input_text: der Original-Chattext (zur Nachvollziehbarkeit)
    """
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
    payload = json.dumps({
        "day": day_str,
        "source": "chat",
        "input_text": input_text,
        "items": [{"food_name": it["name"], "grams": float(it["grams"])} for it in items if it.get("name") and it.get("grams")]
    })
    headers = {"Content-Type": "application/json"}
    conn.request("POST", "/meals/ingest", body=payload, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8")
    try:
        j = json.loads(data) if data else {}
    except Exception:
        j = {"raw": data}

    if resp.status >= 300:
        # Durchreichen – der Client sieht exakt, warum es nicht geklappt hat
        raise HTTPException(status_code=resp.status, detail=j if j else data)
    return j

# ---------- Simple local embedding client (optional) ----------
def _embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Optionaler Embedding-Call. Wenn RAG_EMBED_URL nicht gesetzt, None zurückgeben."""
    if not RAG_EMBED_URL:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(RAG_EMBED_URL, data=json.dumps({"texts": texts}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as f:
            vecs = json.loads(f.read()).get("vectors")
            return vecs
    except Exception:
        return None

def _cosine(a: List[float], b: List[float]) -> float:
    num = sum(x*y for x, y in zip(a, b))
    da = math.sqrt(sum(x*x for x in a))
    db = math.sqrt(sum(y*y for y in b))
    return num / (da*db + 1e-9)

# ==================== Helpers ====================

def _food_list_for_prompt(session: Session, top_n: int = 24) -> List[Food]:
    foods = session.exec(select(Food)).all()
    def score(f: Food):
        if getattr(f, "kcal", 0) <= 0:
            return 0
        return (getattr(f, "protein_g", 0) / getattr(f, "kcal", 1)) * 100.0
    foods_sorted = sorted(foods, key=score, reverse=True)
    return foods_sorted[:top_n]

def _macros_from_food(f: Food, grams: float) -> MacroTotals:
    factor = grams / 100.0
    return MacroTotals(
        kcal=float((getattr(f, "kcal", 0) or 0) * factor),
        protein_g=float((getattr(f, "protein_g", 0) or 0) * factor),
        carbs_g=float((getattr(f, "carbs_g", 0) or 0) * factor),
        fat_g=float((getattr(f, "fat_g", 0) or 0) * factor),
    )

def _mk_goal_kcal(base_kcal: float, goal: Literal["cut","maintain","bulk"], goal_mode: Literal["percent","kcal","rate"],
                  percent: float, offset_kcal: float, rate_kg_per_week: float) -> float:
    """
    - percent: ±(percent * base_kcal)
    - kcal: ±offset_kcal
    - rate: ±(rate_kg_per_week * 7700 / 7) ~ kcal/Tag (7700 kcal ~ 1 kg)
    """
    add = 0.0
    if goal == "maintain":
        return base_kcal
    if goal_mode == "percent":
        add = base_kcal * (abs(percent) / 100.0)
    elif goal_mode == "kcal":
        add = abs(offset_kcal)
    else:  # rate
        add = abs(rate_kg_per_week) * 7700.0 / 7.0
    return base_kcal + (add if goal == "bulk" else -add)

def _apply_prefs_filter_foods(foods: List[Food], prefs: Prefs) -> List[Food]:
    # Minimaler Filter; erweitere bei Bedarf um Tags/Spalten
    res = []
    for f in foods:
        name = (getattr(f, "name", "") or "").lower()
        ok = True
        if prefs.vegan and any(k in name for k in ["quark","joghurt","käse","milch","hähnchen","pute","fisch","ei"]):
            ok = False
        if prefs.veggie and any(k in name for k in ["hähnchen","pute","rind","schwein","fisch","thunfisch","lachs"]):
            ok = False
        if prefs.no_pork and "schwein" in name:
            ok = False
        if prefs.lactose_free and any(k in name for k in ["milch","joghurt","quark","käse"]) and "laktosefrei" not in name:
            ok = False
        if prefs.gluten_free and any(k in name for k in ["weizen","brot","nudel","hafer (nicht gf)"]):
            # Hinweis: ohne Zutatenliste nur Heuristik
            pass
        if prefs.allergens_avoid:
            for a in prefs.allergens_avoid:
                if a.lower() in name:
                    ok = False
                    break
        if ok:
            res.append(f)
    return res

def _retrieve_candidates(session: Session, prefs: Prefs, top_k: int = RAG_TOP_K) -> List[Dict[str, Any]]:
    """
    RAG-Kandidaten:
    - Wenn Recipe/RecipeItem existieren: Rezepte mit aggregierten Nährwerten (100g-basiert hochgerechnet).
    - Sonst: Foods.
    Optional: Embedding-Ranking via RAG_EMBED_URL; Fallback: protein-dichte & einfache Heuristik.
    """
    candidates: List[Dict[str, Any]] = []

    if HAS_RECIPES:
        # hole Rezepte + Items
        recipes = session.exec(select(Recipe)).all()
        for r in recipes:
            # leichte Beschreibung als RAG-Text
            text = f"{r.name} {getattr(r, 'tags', '')}"
            candidates.append({
                "type": "recipe",
                "id": r.id,
                "name": r.name,
                "text": text,
            })
    else:
        foods = session.exec(select(Food)).all()
        foods = _apply_prefs_filter_foods(foods, prefs)
        for f in foods:
            text = f"{f.name} protein {getattr(f,'protein_g',0)} carbs {getattr(f,'carbs_g',0)} fat {getattr(f,'fat_g',0)} kcal {getattr(f,'kcal',0)}"
            candidates.append({
                "type": "food",
                "id": f.id,
                "name": f.name,
                "text": text,
                "kcal_100g": float(getattr(f,"kcal",0) or 0),
                "protein_g_100g": float(getattr(f,"protein_g",0) or 0),
                "carbs_g_100g": float(getattr(f,"carbs_g",0) or 0),
                "fat_g_100g": float(getattr(f,"fat_g",0) or 0),
            })

    # Embedding-Ranking, wenn verfügbar
    vecs = _embed_texts([c["text"] for c in candidates]) if candidates else None
    if vecs:
        q_vecs = _embed_texts(["high protein simple snack balanced macros"])
        if q_vecs:
            qv = q_vecs[0]
            scored = [(c, _cosine(qv, v)) for c, v in zip(candidates, vecs)]
            scored.sort(key=lambda x: x[1], reverse=True)
            candidates = [c for c, _ in scored[:top_k]]
        else:
            candidates = candidates[:top_k]
    else:
        # Fallback Heuristik: protein-dichte, dann kcal-Nähe
        if candidates and candidates[0]["type"] == "food":
            candidates.sort(key=lambda c: (c["protein_g_100g"] / (c["kcal_100g"]+1e-6)) if c["kcal_100g"]>0 else 0, reverse=True)
        candidates = candidates[:top_k]

    return candidates

def _parse_llm_json(raw: str) -> Dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise HTTPException(status_code=500, detail="KI-Ausgabe nicht parsebar.")
    return json.loads(raw[start:end+1])

# ==================== Endpoints ====================

@router.get("/gaps", response_model=GapsResponse)
def gaps(
    day: date = Query(...),
    body_weight_kg: Optional[float] = Query(None, ge=0.0),
    goal: Literal["cut","maintain","bulk"] = Query("maintain"),
    protein_g_per_kg: float = Query(1.8, ge=1.2, le=2.4),
    # Neue, skalierbare Zielsteuerung:
    goal_mode: Literal["percent","kcal","rate"] = Query("percent"),
    goal_percent: float = Query(10.0, ge=0.0, le=25.0, description="+/-% vom TDEE bei bulk/cut"),
    goal_kcal_offset: float = Query(300.0, ge=0.0, le=1000.0),
    goal_rate_kg_per_week: float = Query(0.5, ge=0.1, le=1.0),
    session: Session = Depends(get_session),
):
    intake = _intake_for_day(session, day)
    target = None
    notes: List[str] = []

    if body_weight_kg is not None:
        active_min = _active_minutes_for_day(session, day)
        base_kcal = _target_kcal_for_day(body_weight_kg, active_min) or 0.0

        adj_kcal = _mk_goal_kcal(
            base_kcal=base_kcal,
            goal=goal,
            goal_mode=goal_mode,
            percent=goal_percent,
            offset_kcal=goal_kcal_offset,
            rate_kg_per_week=goal_rate_kg_per_week,
        )

        target_protein = protein_g_per_kg * body_weight_kg
        target = MacroTotals(
            kcal=round(max(adj_kcal, 0.0), 0),
            protein_g=round(max(target_protein, 0.0), 0),
            carbs_g=0.0,
            fat_g=0.0,
        )
        notes.append(f"Ziel kcal via TDEE {round(base_kcal)} & Goal={goal} ({goal_mode}). Protein {protein_g_per_kg} g/kg.")

    remaining = None
    if target:
        remaining = MacroTotals(
            kcal=round(target.kcal - intake.kcal, 1),
            protein_g=round(target.protein_g - intake.protein_g, 1),
            carbs_g=round(target.carbs_g - intake.carbs_g, 1),
            fat_g=round(target.fat_g - intake.fat_g, 1),
        )
        if remaining.kcal <= 0:
            notes.append("Kalorienziel erreicht/überschritten.")
        if remaining.protein_g > 0:
            notes.append("Protein unter Ziel – priorisiere proteinreiche Auswahl.")

    return GapsResponse(day=day, target=target, intake=intake, remaining=remaining, notes=notes)

@router.get("/recommendations", response_model=RecommendationsResponse)
def recommendations(
    day: date = Query(...),
    body_weight_kg: float = Query(..., ge=0.0),
    goal: Literal["cut","maintain","bulk"] = Query("maintain"),
    protein_g_per_kg: float = Query(1.8, ge=1.2, le=2.4),
    max_suggestions: int = Query(4, ge=1, le=8),
    mode: Literal["db","open","rag","hybrid"] = Query("rag"),
    # Präferenzen (leichtgewichtige Übergabe per Query; alternativ /profile persistieren):
    veggie: Optional[bool] = None,
    vegan: Optional[bool] = None,
    no_pork: Optional[bool] = None,
    lactose_free: Optional[bool] = None,
    gluten_free: Optional[bool] = None,
    allergens_avoid: Optional[str] = Query(None, description="Komma-getrennt"),
    budget_level: Optional[Literal["low","mid","high"]] = None,
    cuisine_bias: Optional[str] = Query(None, description="Komma-getrennt, z.B. de,med,asian"),
    session: Session = Depends(get_session),
):
    # 1) Gaps
    gaps_resp = gaps(day=day, body_weight_kg=body_weight_kg, goal=goal, protein_g_per_kg=protein_g_per_kg, session=session)
    if not gaps_resp.remaining:
        raise HTTPException(status_code=400, detail="Keine offenen Lücken – Ziel bereits erreicht.")
    remaining = gaps_resp.remaining

    prefs = Prefs(
        veggie=veggie, vegan=vegan, no_pork=no_pork, lactose_free=lactose_free,
        gluten_free=gluten_free,
        allergens_avoid=[s.strip() for s in allergens_avoid.split(",")] if allergens_avoid else None,
        budget_level=budget_level,
        cuisine_bias=[s.strip() for s in cuisine_bias.split(",")] if cuisine_bias else None,
    )

    # 2) Kandidaten (RAG / DB)
    foods_brief: List[Dict[str, Any]] = []
    rag_ctx: List[Dict[str, Any]] = []

    if mode in ("db", "hybrid"):
        foods = _apply_prefs_filter_foods(_food_list_for_prompt(session, top_n=48), prefs)
        foods_brief = [
            {
                "name": f.name,
                "kcal_100g": float(getattr(f, "kcal", 0) or 0),
                "protein_g_100g": float(getattr(f, "protein_g", 0) or 0),
                "carbs_g_100g": float(getattr(f, "carbs_g", 0) or 0),
                "fat_g_100g": float(getattr(f, "fat_g", 0) or 0),
            } for f in foods
        ]

    if mode in ("rag", "hybrid"):
        rag_ctx = _retrieve_candidates(session, prefs, top_k=RAG_TOP_K)

    # 3) Prompt (RAG-first)
    remaining_json = json.dumps(remaining.model_dump(), ensure_ascii=False)
    prefs_json = json.dumps(prefs.model_dump(), ensure_ascii=False)

    base_instructions = (
        f"Erstelle {max_suggestions} alltagstaugliche Vorschlagskarten (1–3 Zutaten) in DE, "
        "um die Rest-Makros möglichst gut zu treffen. "
        "Gib NUR JSON im Format:\n"
        "{\n  \"suggestions\": [\n    {\"name\":\"...\",\"items\":[{\"food\":\"...\",\"grams\":123}],"
        " \"est_kcal\":..., \"est_protein_g\":..., \"est_carbs_g\":..., \"est_fat_g\":...}\n  ]\n}\n"
        "Regeln: metrische Einheiten (g), realistische Mengen (50–400 g je Zutat), keine Erklärtexte außerhalb JSON, "
        "Protein priorisieren bei Unterdeckung, Kalorienziel respektieren."
    )

    context_blocks = []
    if rag_ctx:
        context_blocks.append("RAG_KANDIDATEN:\n" + json.dumps(rag_ctx, ensure_ascii=False))
    if foods_brief:
        context_blocks.append("FOODS_DB:\n" + json.dumps(foods_brief, ensure_ascii=False))

    context_str = "\n\n".join(context_blocks) if context_blocks else "KEIN_KONTEXT"

    prompt = (
        base_instructions
        + f"\n\nREMAINING:\n{remaining_json}\n\nPREFERENCES:\n{prefs_json}\n\nKONTEXT:\n{context_str}\n"
        + ("Bevorzuge Kandidaten aus RAG_KANDIDATEN, verwende exakte Namen wenn vorhanden. "
           "Fülle Makros pragmatisch (keine überlangen Rezepte).")
    )

    # 4) LLM call
    raw = _ollama_generate(prompt, as_json=True)
    data = _parse_llm_json(raw)

    # 5) Parse + Quelle
    suggestions: List[Suggestion] = []
    fb_names = {f["name"] for f in foods_brief} if foods_brief else set()
    rag_names = {c["name"] for c in rag_ctx} if rag_ctx else set()

    for s in data.get("suggestions", []):
        items: List[SuggestionItem] = []
        for it in s.get("items", []):
            try:
                food_name = (it.get("food") or "").strip()
                grams = float(it.get("grams", 0))
            except Exception:
                continue
            if not food_name or grams <= 0:
                continue
            items.append(SuggestionItem(food=food_name, grams=grams))

        if not items:
            continue

        # Quelle bestimmen
        if any(it.food in rag_names for it in items):
            src = "rag"
        elif any(it.food in fb_names for it in items):
            src = "db"
        else:
            src = "llm"

        suggestions.append(Suggestion(
            name=s.get("name", "Vorschlag"),
            items=items,
            source=src,
            est_kcal=s.get("est_kcal"),
            est_protein_g=s.get("est_protein_g"),
            est_carbs_g=s.get("est_carbs_g"),
            est_fat_g=s.get("est_fat_g"),
        ))

    if not suggestions:
        raise HTTPException(status_code=500, detail="Keine verwertbaren Vorschläge erhalten.")

    return RecommendationsResponse(day=day, remaining=remaining, mode=mode, suggestions=suggestions)

# ============ NEU: Chat-Endpunkt im Advisor (wie ChatGPT) ============

class ChatRequest(BaseModel):
    message: str = Field(..., description="Benutzereingabe (Frage/Aufgabe)")
    context: Optional[str] = Field(
        default=None,
        description="Optional: zusätzlicher Kontext (z.B. Tagesdaten, Ziele, Präferenzen)."
    )
    json_mode: bool = Field(False, description="Wenn true, bitte strikt JSON zurückgeben (z.B. für Tools).")

class ChatResponse(BaseModel):
    output: str
    used_backend: Literal["llama_cpp","ollama_http","ollama_cli"] = "ollama_http"

@router.post("/chat", response_model=ChatResponse)
def advisor_chat(
    payload: ChatRequest,
):
    """
    Generischer Chat-Endpoint, der lokal ein LLM nutzt (in-process oder Ollama),
    um 'wie ChatGPT' zu antworten – ohne Cloud.
    """
    prompt = build_chat_prompt(payload.message, payload.context)
    # wenn json_mode=True → versuche JSON-Strict
    try:
        text = _llm_generate(prompt, as_json=payload.json_mode)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM-Fehler: {e!s}")

    # Heuristik: Backend ableiten (nur kosmetisch, optional)
    backend = "ollama_http"
    if LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(LLAMA_CPP_MODEL_PATH):
        backend = "llama_cpp"

    return ChatResponse(output=text, used_backend=backend)


# ============ KI-first Compose (Freitext -> strukturierte Ideen) ============


class Macro(BaseModel):
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float

class Ingredient(BaseModel):
    name: str
    grams: Optional[float] = None
    note: Optional[str] = None

class RecipeIdea(BaseModel):
    title: str
    time_minutes: Optional[int] = None
    difficulty: Optional[Literal["easy","medium","hard"]] = "easy"
    # kein ungültiger Default (vermeidet Schema-Warnungen)
    ingredients: List[Ingredient] = Field(default_factory=list)
    instructions: List[str]
    macros: Optional[Macro] = None
    tags: List[str] = []

class ComposeRequest(BaseModel):
    message: str = Field(..., description="Freitext: z.B. 'proteinreiches Abendessen <800 kcal, vegetarisch'")
    day: Optional[date] = None
    body_weight_kg: Optional[float] = None
    servings: int = 1
    preferences: List[str] = []  # ["vegetarian","vegan","no_pork","lactose_free","budget","german","italian",...]

class ComposeResponse(BaseModel):
    constraints: Dict[str, Any]
    ideas: List[RecipeIdea]
    notes: List[str] = []

def _constraints_from_context(session: Session, req: ComposeRequest) -> Dict[str, Any]:
    c = {"max_kcal": None, "protein_bias": False}
    if req.day and req.body_weight_kg:
        intake = _intake_for_day(session, req.day)
        actmin = _active_minutes_for_day(session, req.day)
        target = _target_kcal_for_day(req.body_weight_kg, actmin) or 0.0
        remaining = target - intake.kcal
        prot_target = 2.0 * req.body_weight_kg
        c.update({
            "target_kcal": round(target, 0),
            "remaining_kcal": round(remaining, 0),
            "protein_target_g": round(prot_target, 0),
        })
        c["protein_bias"] = (prot_target - intake.protein_g) > 25
        c["max_kcal"] = max(400, min(900, remaining + 200)) if remaining > 0 else 650
    return c

def _tighten_with_foods_db(session: Session, idea: RecipeIdea) -> RecipeIdea:
    """Wenn Zutaten exakt in Food vorkommen, präzisiere Makros."""
    kcal = p = c = f = 0.0
    hit = False
    for ing in idea.ingredients:
        if ing.grams and ing.grams > 0:
            fobj = session.exec(select(Food).where(Food.name == ing.name)).first()
            if fobj:
                factor = ing.grams/100.0
                kcal += (fobj.kcal or 0.0) * factor
                p    += (fobj.protein_g or 0.0) * factor
                c    += (fobj.carbs_g  or 0.0) * factor
                f    += (fobj.fat_g    or 0.0) * factor
                hit = True
    if hit:
        idea.macros = Macro(kcal=round(kcal,1), protein_g=round(p,1), carbs_g=round(c,1), fat_g=round(f,1))
    return idea


def _prefs_from_compose(req: ComposeRequest) -> Prefs:
    pref_set = set(req.preferences or [])
    cuisine_map = {"german": "german", "italian": "italian", "asian": "asian"}
    cuisine_bias = [cuisine_map[p] for p in pref_set if p in cuisine_map]
    return Prefs(
        veggie=True if "vegetarian" in pref_set else None,
        vegan=True if "vegan" in pref_set else None,
        no_pork=True if "no_pork" in pref_set else None,
        lactose_free=True if "lactose_free" in pref_set else None,
        gluten_free=True if "gluten_free" in pref_set else None,
        allergens_avoid=None,
        budget_level="low" if "budget" in pref_set else None,
        cuisine_bias=cuisine_bias or None,
    )


def _fallback_title(main_food: Food, message_hint: str, idx: int) -> str:
    name = getattr(main_food, "name", "Idee").strip()
    hint = message_hint.lower()
    if "fruehstueck" in hint or "fruhstuck" in hint:
        return f"Proteinreiches Fruehstueck mit {name}"
    if "salat" in hint:
        return f"{name}-Salat-Bowl"
    if "snack" in hint:
        return f"Schneller Snack: {name}"
    if "mittag" in hint or "lunch" in hint:
        return f"Schnelles Mittag: {name}"
    if "abend" in hint or "dinner" in hint:
        return f"Abendessen: {name}"
    return f"Idee {idx+1}: {name}"

def _fallback_instructions(main_food: Food, sides: List[Food]) -> List[str]:
    steps = [
        f"{getattr(main_food, 'name', 'Hauptzutat')} portionsgerecht zubereiten (anbraten, backen oder daempfen)."
    ]
    if sides:
        steps.append("Beilagen garen oder frisch anrichten und nach Bedarf wuerzen.")
    steps.append("Alles zusammen anrichten, abschmecken und servieren.")
    return steps

def _respect_max_kcal(session: Session, idea: RecipeIdea, max_kcal: Optional[float]) -> RecipeIdea:
    if not max_kcal or not idea.macros or idea.macros.kcal <= max_kcal:
        return idea
    if idea.macros.kcal <= 0:
        return idea
    scale = max_kcal / idea.macros.kcal
    scale = max(scale, 0.4)  # nicht zu extrem reduzieren
    changed = False
    for ing in idea.ingredients:
        if ing.grams and ing.grams > 0:
            ing.grams = round(max(40.0, ing.grams * scale), 1)
            changed = True
    if changed:
        idea = _tighten_with_foods_db(session, idea)
    return idea


def _combo_matches_preferences(ingredients: List[Ingredient], prefs: Prefs) -> bool:
    def _name_has(substrs: List[str], name: str) -> bool:
        lower = name.lower()
        return any(s in lower for s in substrs)

    if prefs.vegan:
        for ing in ingredients:
            if _name_has(["huhn", "puten", "rind", "lachs", "fisch", "ei", "joghurt", "skyr", "kaese", "quark"], ing.name):
                return False
    elif prefs.veggie:
        for ing in ingredients:
            if _name_has(["huhn", "puten", "rind", "lachs", "schinken", "speck", "fisch"], ing.name):
                return False

    if prefs.no_pork:
        for ing in ingredients:
            if _name_has(["schwein", "schinken", "speck"], ing.name):
                return False

    if prefs.lactose_free:
        for ing in ingredients:
            if _name_has(["milch", "joghurt", "skyr", "kaese", "quark", "butter"], ing.name) and "laktosefrei" not in ing.name.lower():
                return False

    return True


def _combo_score(meta: Dict[str, Any], message_hint: str, prefs: Prefs) -> float:
    score = 0.0
    kind = meta.get("kind")
    tags = meta.get("tags", [])
    hint = message_hint

    if kind == "breakfast" and any(k in hint for k in ["frueh", "breakfast", "morg"]):
        score += 3.0
    if kind == "snack" and "snack" in hint:
        score += 2.5
    if kind in ("lunch", "dinner") and any(k in hint for k in ["mittag", "lunch", "abend", "dinner"]):
        score += 2.5

    if prefs.cuisine_bias:
        if any(tag in prefs.cuisine_bias for tag in tags):
            score += 1.5
        else:
            score -= 0.5

    if prefs.budget_level == "low" and meta.get("cost") == "low":
        score += 0.5

    # Light preference for bowls if user mentions "bowl"
    if "bowl" in hint and "bowl" in tags:
        score += 1.0

    return score


def _generic_fallback_ideas(req: ComposeRequest, prefs: Prefs) -> List[RecipeIdea]:
    message_hint = (req.message or "").lower()

    combos: List[Dict[str, Any]] = [
        {
            "title": "Tofu-Gemuese-Pfanne",
            "ingredients": [("Tofu natur", 200.0), ("Brokkoli", 120.0), ("Paprika", 80.0), ("Sesamoel", 10.0)],
            "instructions": [
                "Tofu in Wuerfel schneiden und in etwas Oel knusprig anbraten.",
                "Gemuese zugeben, wuerzen und bissfest garen."
            ],
            "tags": ["vegan", "warm", "pfanne", "asian"],
            "kind": "dinner",
            "diet": "vegan",
            "cost": "low",
        },
        {
            "title": "Kichererbsen-Quinoa-Bowl",
            "ingredients": [("Kichererbsen (Dose)", 160.0), ("Quinoa gekocht", 140.0), ("Gurkenwuerfel", 80.0), ("Babyspinat", 50.0), ("Olivenoel", 12.0)],
            "instructions": [
                "Quinoa nach Packungsangabe garen.",
                "Kichererbsen abspuelen, mit Gemuese und Spinat mischen, mit Oel und Zitrone abschmecken."
            ],
            "tags": ["vegan", "bowl", "mediterran"],
            "kind": "lunch",
            "diet": "vegan",
            "cost": "low",
        },
        {
            "title": "Hafer-Beeren-Fruehstueck",
            "ingredients": [("Haferflocken", 60.0), ("Pflanzendrink", 200.0), ("Beerenmischung", 120.0), ("Mandeln gehackt", 20.0)],
            "instructions": [
                "Haferflocken mit Pflanzendrink kurz erhitzen oder ueber Nacht einweichen.",
                "Mit Beeren und Mandeln toppen."
            ],
            "tags": ["fruehstueck", "vegetarisch", "bowl"],
            "kind": "breakfast",
            "diet": "vegetarian",
            "cost": "low",
        },
        {
            "title": "Huehnchen mit Ofengemuese",
            "ingredients": [("Huhnbrustfilet", 180.0), ("Suesse Kartoffel", 150.0), ("Zucchini", 120.0), ("Olivenoel", 12.0)],
            "instructions": [
                "Gemuese wuerfeln, mit Oel und Gewuerzen vermengen und im Ofen roesten.",
                "Huehnchen wuerzen und mit backen oder separat anbraten."
            ],
            "tags": ["warm", "deftig", "german"],
            "kind": "dinner",
            "diet": "omnivore",
            "cost": "mid",
        },
        {
            "title": "Linsen-Nudel-Salat",
            "ingredients": [("Linsennudeln gekocht", 150.0), ("Cherrytomaten", 100.0), ("Rucola", 40.0), ("Feta (optional)", 40.0), ("Olivenoel", 12.0)],
            "instructions": [
                "Nudeln kochen, kalt abschrecken.",
                "Mit Tomaten, Rucola und Dressing vermischen, optional Feta dazugeben."
            ],
            "tags": ["lunch", "bowl", "mediterran"],
            "kind": "lunch",
            "diet": "vegetarian",
            "cost": "low",
        },
        {
            "title": "Avocado-Vollkorn-Toast",
            "ingredients": [("Vollkorntoast", 70.0), ("Avocado", 80.0), ("Cherrytomaten", 60.0), ("Kresse", 5.0), ("Zitronensaft", 10.0)],
            "instructions": [
                "Toast roesten, Avocado zerdruecken und mit Zitronensaft, Salz und Pfeffer abschmecken.",
                "Auf Toast streichen, mit Tomaten und Kresse belegen."
            ],
            "tags": ["snack", "vegetarisch"],
            "kind": "snack",
            "diet": "vegetarian",
            "cost": "mid",
        },
    ]

    ingredient_objs_template = [
        [Ingredient(name=name, grams=grams) for name, grams in combo["ingredients"]]
        for combo in combos
    ]

    available_combos: List[Dict[str, Any]] = []
    for combo, ingredients in zip(combos, ingredient_objs_template):
        if _combo_matches_preferences(ingredients, prefs):
            combo_copy = dict(combo)
            combo_copy["ingredients_obj"] = ingredients
            available_combos.append(combo_copy)

    # Wenn nichts passt (z.B. sehr strenge Preferences), setze alle, aber ohne Problemzutaten
    if not available_combos:
        for combo, ingredients in zip(combos, ingredient_objs_template):
            filtered = []
            for ing in ingredients:
                if prefs.vegan and any(k in ing.name.lower() for k in ["huhn", "feta", "skyr", "huhnbrust", "huehn"]):
                    continue
                if prefs.lactose_free and "feta" in ing.name.lower():
                    continue
                filtered.append(ing)
            combo_copy = dict(combo)
            combo_copy["ingredients_obj"] = filtered or ingredients
            available_combos.append(combo_copy)

    available_combos.sort(key=lambda c: _combo_score(c, message_hint, prefs), reverse=True)

    ideas: List[RecipeIdea] = []
    for combo in available_combos:
        ingredients = [Ingredient(name=ing.name, grams=ing.grams) for ing in combo["ingredients_obj"]]
        idea = RecipeIdea(
            title=combo["title"],
            time_minutes=20 if combo["kind"] != "breakfast" else 10,
            difficulty="easy",
            ingredients=ingredients,
            instructions=combo["instructions"],
            tags=["fallback", "ohne_llm"] + combo.get("tags", []),
        )
        ideas.append(idea)
        if len(ideas) >= 3:
            break

    return ideas


def _compose_fallback_ideas(
    session: Session, req: ComposeRequest, constraints: Dict[str, Any], prefs: Prefs
) -> List[RecipeIdea]:
    foods_pool = _apply_prefs_filter_foods(_food_list_for_prompt(session, top_n=36), prefs)
    if not foods_pool:
        foods_pool = _apply_prefs_filter_foods(session.exec(select(Food)).all(), prefs)
    if not foods_pool:
        return _generic_fallback_ideas(req, prefs)

    ideas: List[RecipeIdea] = []
    hint = (req.message or "").lower()

    for idx, main in enumerate(foods_pool[:3]):
        sides: List[Food] = []
        for offset in range(1, len(foods_pool)):
            cand = foods_pool[(idx + offset) % len(foods_pool)]
            if cand is main or cand in sides:
                continue
            sides.append(cand)
            if len(sides) >= 2:
                break

        main_protein = float(getattr(main, "protein_g", 0.0) or 0.0)
        main_grams = 180.0 if main_protein >= 20.0 else 200.0
        ingredients = [Ingredient(name=getattr(main, "name", "Hauptzutat"), grams=round(main_grams, 1))]

        for side in sides:
            carbs = float(getattr(side, "carbs_g", 0.0) or 0.0)
            protein = float(getattr(side, "protein_g", 0.0) or 0.0)
            grams = 120.0 if carbs >= protein else 90.0
            ingredients.append(Ingredient(name=getattr(side, "name", "Beilage"), grams=round(grams, 1)))

        idea = RecipeIdea(
            title=_fallback_title(main, hint, idx),
            time_minutes=20,
            difficulty="easy",
            ingredients=ingredients,
            instructions=_fallback_instructions(main, sides),
            tags=["fallback", "ohne_llm"],
        )
        idea = _tighten_with_foods_db(session, idea)
        idea = _respect_max_kcal(session, idea, constraints.get("max_kcal"))

        pref_tags: List[str] = []
        if prefs.vegan:
            pref_tags.append("vegan")
        elif prefs.veggie:
            pref_tags.append("vegetarisch")
        if prefs.cuisine_bias:
            pref_tags.extend(prefs.cuisine_bias)
        if prefs.no_pork:
            pref_tags.append("ohne_schwein")
        if pref_tags:
            seen = set(idea.tags)
            for tag in pref_tags:
                if tag not in seen:
                    idea.tags.append(tag)
                    seen.add(tag)

        ideas.append(idea)

    return ideas

@router.post("/compose", response_model=ComposeResponse)
def compose(req: ComposeRequest, session: Session = Depends(get_session)):
    constraints = _constraints_from_context(session, req)
    prefs = _prefs_from_compose(req)

    # Vorab: Wenn kein lokales LLM erreichbar ist, heuristischen Fallback versuchen
    has_local_llm = bool(LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(LLAMA_CPP_MODEL_PATH))
    if not has_local_llm and not _ollama_alive(timeout=2):
        fallback_ideas = _compose_fallback_ideas(session, req, constraints, prefs)
        if fallback_ideas:
            return ComposeResponse(
                constraints=constraints,
                ideas=fallback_ideas,
                notes=["Fallback-Modus: Vorschlaege aus lokaler Food-Datenbank, da kein LLM erreichbar war."]
            )
        return JSONResponse(
            status_code=503,
            content={
                "error": "llm_unavailable",
                "detail": "Kein lokales LLM erreichbar und keine lokalen Rezept-Heuristiken verfuegbar. Bitte Ollama starten oder Food-Datenbank befuellen."
            }
        )

    system = (
        "Du bist ein praeziser deutschsprachiger Ernaehrungscoach. "
        "Liefere 3 praktische Rezeptideen mit Zutaten (in g), klaren Schritten und geschaetzten Makros pro Portion. "
        "Beachte Praeferenzen (vegetarian/vegan/no_pork/lactose_free/budget/kitchen=italian,german,...). "
        "Antworte ausschliesslich als JSON in dem angegebenen Format."
    )
    prefs_payload = prefs.model_dump(exclude_none=True)
    user = f"""
Nutzeranfrage: {req.message}
Servings: {req.servings}
Praeferenzen: {json.dumps(prefs_payload, ensure_ascii=False) if prefs_payload else "keine"}
Constraints: {json.dumps(constraints, ensure_ascii=False)}
JSON-Format:
{{
  "ideas": [
    {{
      "title": "...",
      "time_minutes": 20,
      "difficulty": "easy",
      "ingredients": [{{"name":"...", "grams":120}}, ...],
      "instructions": ["Schritt 1 ...","Schritt 2 ..."],
      "macros": {{"kcal": ..., "protein_g": ..., "carbs_g": ..., "fat_g": ...}},
      "tags": ["proteinreich","unter_800_kcal"]
    }},
    ...
  ]
}}
Regeln: metrisch, 50-400 g/Zutat, pro Portion <= max_kcal falls gesetzt. Keine Erklaertexte ausserhalb des JSON.
"""

    # ---- LLM call + JSON-Parsing robust ----
    try:
        try:
            # Preferred: /api/chat mit sauberem JSON (falls utils vorhanden)
            from app.utils.llm import llm_generate_json  # optional
            raw_ideas = llm_generate_json(system, user, model=OLLAMA_MODEL,
                                          endpoint=f"http://{OLLAMA_HOST}:{OLLAMA_PORT}",
                                          json_root="ideas")
        except Exception:
            # Fallback: /api/generate format='json'
            raw = _ollama_generate(f"{system}\n\n{user}", as_json=True, timeout=OLLAMA_TIMEOUT)
            # Versuch JSON parsen (mit deinem Helfer)
            data = _parse_llm_json(raw)
            raw_ideas = data.get("ideas", [])

        if not isinstance(raw_ideas, list):
            raise ValueError("LLM lieferte kein ideas-Array.")
    except HTTPException:
        raise
    except Exception as e:
        # Immer JSON-Fehler liefern (nicht HTML)
        return JSONResponse(
            status_code=502,
            content={"error": "compose_llm_failed", "detail": str(e)}
        )

    # ---- Validieren & Makros ggf. präzisieren ----
    ideas: List[RecipeIdea] = []
    try:
        from app.utils.validators import clamp, safe_float
    except Exception:
        # fallback inline
        clamp = lambda x, lo, hi: max(lo, min(hi, x))
        def safe_float(x):
            try: return float(x)
            except: return 0.0

    for idead in raw_ideas:
        try:
            idea = RecipeIdea(**idead)
        except Exception as e:
            # eine kaputte Idee überspringen, aber nicht komplett fehlschlagen
            continue
        if idea.macros:
            idea.macros.kcal      = clamp(safe_float(idea.macros.kcal), 0, 1400)
            idea.macros.protein_g = clamp(safe_float(idea.macros.protein_g), 0, 200)
            idea.macros.carbs_g   = clamp(safe_float(idea.macros.carbs_g), 0, 250)
            idea.macros.fat_g     = clamp(safe_float(idea.macros.fat_g), 0, 120)
        idea = _tighten_with_foods_db(session, idea)
        ideas.append(idea)

    if not ideas:
        return JSONResponse(
            status_code=502,
            content={"error": "no_ideas", "detail": "LLM lieferte keine verwertbaren Ideen."}
        )

    notes = []
    if constraints.get("max_kcal"):
        over = [i.title for i in ideas if i.macros and i.macros.kcal > constraints["max_kcal"]]
        if over:
            notes.append(f"Ideen > max_kcal ({constraints['max_kcal']}): {', '.join(over)}")

    return ComposeResponse(constraints=constraints, ideas=ideas, notes=notes)
