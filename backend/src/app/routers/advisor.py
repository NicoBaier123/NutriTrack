# backend/app/routers/advisor.py
from __future__ import annotations
from datetime import date
from typing import List, Optional, Literal, Dict, Any, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select
import http.client, json, os, math, re
import subprocess
from typing import Tuple
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
import json, http.client, os

from app.core.config import get_settings
from app.core.database import get_session
from app.models.foods import Food
from app.models.meals import Meal, MealItem
from app.routers.summary import _intake_for_day, _active_minutes_for_day, _target_kcal_for_day

# --- Optional: Rezepte, falls vorhanden (sonst stiller Fallback auf Foods) ---
try:
    from app.models.recipes import Recipe, RecipeItem
    HAS_RECIPES = True
except Exception:
    HAS_RECIPES = False

# --- Modular RAG system ---
try:
    from app.rag.indexer import RecipeIndexer, RecipeEmbedding
    from app.rag.preprocess import QueryPreprocessor
    from app.rag.postprocess import PostProcessor
    RAG_MODULES_AVAILABLE = True
except Exception:
    RAG_MODULES_AVAILABLE = False

router = APIRouter(prefix="/advisor", tags=["advisor"])
SETTINGS = get_settings()

# ==================== Modelle ====================

class MacroTotals(BaseModel):
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0

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
    est_fiber_g: Optional[float] = None

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
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "100"))

RAG_EMBED_URL = os.getenv("RAG_EMBED_URL")  # z.B. http://127.0.0.1:8001/embed
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "30"))
RAG_MAX_RECIPES = int(os.getenv("RAG_MAX_RECIPES", "0"))  # 0 => keine Limitierung

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


SYSTEM_PROMPT_CHAT = (
    "Du bist ein hilfsbereiter, praeziser Ernährungs- und Fitnessassistent. "
    "Antworte knapp, klar und mit konkreten Zahlen, wenn sinnvoll. "
    "Wenn dir Informationen fehlen, nenne explizit, was du brauchst. "
    "Keine Halluzinationen: sei ehrlich, wenn du etwas nicht weißt."
)

def build_chat_prompt(user_message: str, extra_context: Optional[str] = None) -> str:
    ctx = (extra_context or "").strip()
    if ctx:
        return f"{SYSTEM_PROMPT_CHAT}\n\n[Kontext]\n{ctx}\n\n[Frage]\n{user_message}\n\n[Antwort]"
    return f"{SYSTEM_PROMPT_CHAT}\n\n[Frage]\n{user_message}\n\n[Antwort]"


from fastapi import HTTPException

def _ollama_generate(prompt: str, model: str = OLLAMA_MODEL, as_json: bool = False, timeout=60) -> str | dict:
    conn = http.client.HTTPConnection(OLLAMA_HOST, OLLAMA_PORT, timeout=timeout)
    body = {"model": model, "prompt": prompt, "stream": False}
    if as_json:
        body["format"] = "json"
        body["options"] = {"temperature": 0.3}
    conn.request("POST", "/api/generate", body=json.dumps(body), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    if res.status != 200:
        raise HTTPException(status_code=503, detail=f"Ollama error {res.status}")
    outer = json.loads(res.read())  # {"response": "...", ...}
    text = outer.get("response", "")

    if as_json:
        try:
            return json.loads(text)  # <- hier soll das eigentliche, strukturierte JSON landen
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=503, detail={
                "error": "llm_invalid_json",
                "hint": "Ollama lieferte kein valides JSON im Compose-Mode.",
                "sample": text[:400]
            }) from e
    return text

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
        fiber_g=float((getattr(f, "fiber_g", 0) or 0) * factor),
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
        recipes = session.exec(select(Recipe).options(selectinload(Recipe.ingredients)).order_by(Recipe.created_at.desc()).limit(top_k)).all()
        for r in recipes:
            # leichte Beschreibung als RAG-Text
            title = getattr(r, 'title', '') or ''
            text = f"{title} {getattr(r, 'tags', '')}"
            candidates.append({
                "type": "recipe",
                "id": r.id,
                "name": title,
                "text": text,
                "macros": {
                    "kcal": getattr(r, 'macros_kcal', None),
                    "protein_g": getattr(r, 'macros_protein_g', None),
                    "carbs_g": getattr(r, 'macros_carbs_g', None),
                    "fat_g": getattr(r, 'macros_fat_g', None),
                    "fiber_g": getattr(r, 'macros_fiber_g', None),
                },
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

    # Embedding-Ranking, wenn verfuegbar
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

def _fallback_recommendations_from_foods(
    session: Session,
    prefs: Prefs,
    remaining: Optional[MacroTotals],
    limit: int,
) -> List[Suggestion]:
    """
    Build pragmatic, DB-backed suggestions when no LLM backend is available.
    """
    if remaining is None or limit <= 0:
        return []

    foods = _apply_prefs_filter_foods(_food_list_for_prompt(session, top_n=limit * 4), prefs)
    if not foods:
        foods = _apply_prefs_filter_foods(session.exec(select(Food)).all(), prefs)
    if not foods:
        return []

    per_suggestion_kcal = remaining.kcal / float(limit) if limit else remaining.kcal
    if per_suggestion_kcal <= 0:
        per_suggestion_kcal = 250.0

    suggestions: List[Suggestion] = []
    used_names: set[str] = set()
    side_index = 0

    for primary in foods:
        primary_name = (getattr(primary, "name", "") or "").strip()
        if not primary_name or primary_name in used_names:
            continue

        kcal_100g = float(getattr(primary, "kcal", 0.0) or 0.0)
        if kcal_100g <= 0:
            grams_primary = 120.0
        else:
            grams_primary = (per_suggestion_kcal / kcal_100g) * 100.0
            grams_primary = max(60.0, min(grams_primary, 350.0))

        macro_primary = _macros_from_food(primary, grams_primary)
        items = [SuggestionItem(food=primary_name, grams=round(grams_primary, 1))]

        if len(foods) > 1:
            while side_index < len(foods):
                side = foods[side_index]
                side_index += 1
                side_name = (getattr(side, "name", "") or "").strip()
                if not side_name or side_name == primary_name:
                    continue
                side_grams = min(200.0, max(50.0, 0.4 * grams_primary))
                items.append(SuggestionItem(food=side_name, grams=round(side_grams, 1)))
                macro_side = _macros_from_food(side, side_grams)
                macro_primary.kcal += macro_side.kcal
                macro_primary.protein_g += macro_side.protein_g
                macro_primary.carbs_g += macro_side.carbs_g
                macro_primary.fat_g += macro_side.fat_g
                break

        suggestions.append(
            Suggestion(
                name=f"{primary_name} Teller",
                items=items,
                source="db",
                est_kcal=round(macro_primary.kcal, 1),
                est_protein_g=round(macro_primary.protein_g, 1),
                est_carbs_g=round(macro_primary.carbs_g, 1),
                est_fat_g=round(macro_primary.fat_g, 1),
                est_fiber_g=round(macro_primary.fiber_g, 1),
            )
        )
        used_names.add(primary_name)

        if len(suggestions) >= limit:
            break

    return suggestions



def _merge_ideas(primary: List["RecipeIdea"], secondary: List["RecipeIdea"]) -> List["RecipeIdea"]:
    seen = {idea.title.lower(): idea for idea in primary}
    merged = list(primary)
    for idea in secondary:
        key = idea.title.lower()
        if key not in seen:
            merged.append(idea)
            seen[key] = idea
    return merged

def _persist_recipe_ideas(
    session: Session,
    req: "ComposeRequest",
    prefs: Prefs,
    constraints: Dict[str, Any],
    ideas: List["RecipeIdea"],
    source: str,
) -> None:
    if not HAS_RECIPES or not ideas:
        return

    try:
        prefs_json = json.dumps(prefs.model_dump(exclude_none=True), ensure_ascii=False) if prefs else None
        constraints_json = json.dumps(constraints, ensure_ascii=False) if constraints else None

        for idea in ideas:
            if session.exec(
                select(Recipe).where(
                    Recipe.title == idea.title,
                    Recipe.source == source,
                )
            ).first():
                continue

            instructions_payload = idea.instructions or []
            recipe = Recipe(
                title=idea.title,
                source=source,
                request_message=req.message,
                request_day=req.day,
                request_servings=req.servings,
                preferences_json=prefs_json,
                constraints_json=constraints_json,
                instructions_json=instructions_payload,
                time_minutes=idea.time_minutes,
                difficulty=idea.difficulty,
                tags=",".join(idea.tags or []),
                macros_kcal=(idea.macros.kcal if idea.macros else None),
                macros_protein_g=(idea.macros.protein_g if idea.macros else None),
                macros_carbs_g=(idea.macros.carbs_g if idea.macros else None),
                macros_fat_g=(idea.macros.fat_g if idea.macros else None),
                macros_fiber_g=(idea.macros.fiber_g if idea.macros else None),
            )
            session.add(recipe)
            session.flush()

            for ingredient in idea.ingredients:
                session.add(
                    RecipeItem(
                        recipe_id=recipe.id,
                        name=ingredient.name,
                        grams=ingredient.grams,
                        note=ingredient.note,
                    )
                )
        session.commit()
    except Exception as exc:
        session.rollback()
        print("[WARN] Persisting recipe ideas failed:", exc)


def _recipe_to_idea(recipe: "Recipe") -> "RecipeIdea":
    macros = None
    if (
        recipe.macros_kcal is not None
        and recipe.macros_protein_g is not None
        and recipe.macros_carbs_g is not None
        and recipe.macros_fat_g is not None
    ):
        macros = Macro(
            kcal=float(recipe.macros_kcal),
            protein_g=float(recipe.macros_protein_g),
            carbs_g=float(recipe.macros_carbs_g),
            fat_g=float(recipe.macros_fat_g),
            fiber_g=float(recipe.macros_fiber_g) if recipe.macros_fiber_g is not None else None,
        )

    tags = [t.strip() for t in (recipe.tags or "").split(",") if t.strip()]

    allowed_sources = {"rag", "llm", "fallback", "db"}
    raw_source = (recipe.source or "db").lower()
    source = raw_source if raw_source in allowed_sources else "db"

    return RecipeIdea(
        title=recipe.title,
        time_minutes=recipe.time_minutes,
        difficulty=recipe.difficulty or "easy",
        ingredients=[
            Ingredient(name=ing.name, grams=ing.grams, note=ing.note) for ing in getattr(recipe, "ingredients", [])
        ],
        instructions=list(recipe.instructions_json or []),
        macros=macros,
        tags=tags,
        source=source,
    )


def _idea_to_suggestion(idea: "RecipeIdea", source: str = "db") -> Suggestion:
    effective_source = getattr(idea, "source", None) or source
    return Suggestion(
        name=idea.title,
        items=[SuggestionItem(food=ing.name, grams=ing.grams or 0.0) for ing in idea.ingredients],
        source=effective_source,
        est_kcal=idea.macros.kcal if idea.macros else None,
        est_protein_g=idea.macros.protein_g if idea.macros else None,
        est_carbs_g=idea.macros.carbs_g if idea.macros else None,
        est_fat_g=idea.macros.fat_g if idea.macros else None,
        est_fiber_g=idea.macros.fiber_g if idea.macros else None,
    )


def _ideas_to_suggestions(ideas: List["RecipeIdea"], source: str = "db") -> List[Suggestion]:
    return [_idea_to_suggestion(idea, source=source) for idea in ideas]


def _merge_suggestions(primary: List[Suggestion], secondary: List[Suggestion]) -> List[Suggestion]:
    seen = {suggestion.name.lower(): suggestion for suggestion in primary}
    merged = list(primary)
    for suggestion in secondary:
        key = suggestion.name.lower()
        if key not in seen:
            merged.append(suggestion)
            seen[key] = suggestion
    return merged


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return re.findall(r"[a-z0-9äöüß]+", text.lower())
    

def _infer_required_ingredients(session: Session, message: Optional[str]) -> List[str]:
    if not message:
        return []
    message_tokens = set(_tokenize(message))
    if not message_tokens:
        return []
    names = session.exec(select(Food.name)).all()
    matches: List[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = (raw_name or "").strip()
        if not name:
            continue
        name_tokens = set(_tokenize(name))
        if not name_tokens or not name_tokens <= message_tokens:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        matches.append(name)
    return matches


def _keyword_overlap(query_tokens: List[str], doc_tokens: List[str]) -> float:
    if not query_tokens or not doc_tokens:
        return 0.0
    qs, ds = set(query_tokens), set(doc_tokens)
    return len(qs & ds) / max(len(qs), 1)


def _ingredient_overlap_score(recipe: "Recipe", query_text: str) -> float:
    if not query_text:
        return 0.0
    query_tokens = set(_tokenize(query_text))
    if not query_tokens:
        return 0.0
    ingredient_tokens: set[str] = set()
    for ingredient in getattr(recipe, "ingredients", []) or []:
        ingredient_tokens.update(_tokenize(ingredient.name or ""))
    if not ingredient_tokens:
        return 0.0
    return len(query_tokens & ingredient_tokens) / max(len(query_tokens), 1)


def _nutrition_fit_score(recipe: "Recipe", constraints: Dict[str, Any]) -> float:
    if not constraints or getattr(recipe, "macros_kcal", None) is None:
        return 0.0
    kcal = float(recipe.macros_kcal or 0.0)
    remaining = constraints.get("remaining_kcal")
    max_kcal = constraints.get("max_kcal")
    score = 0.0
    if remaining is not None:
        target = max(remaining, 0.0)
        denom = max(target, 1.0)
        score += max(0.0, 1.0 - abs(kcal - target) / denom)
    if max_kcal is not None:
        if kcal <= max_kcal:
            score += 0.3
        else:
            score -= min(1.0, (kcal - max_kcal) / max(max_kcal, 1.0))
    return score


def _recipe_document(recipe: "Recipe") -> str:
    parts: List[str] = []
    parts.append(recipe.title or "")
    parts.append(recipe.tags or "")
    if recipe.instructions_json:
        parts.extend(recipe.instructions_json)
    for ing in getattr(recipe, "ingredients", []) or []:
        parts.append(f"{ing.name} {ing.grams or ''}".strip())
    macro_bits: List[str] = []
    if recipe.macros_kcal:
        macro_bits.append(f"{recipe.macros_kcal} kcal")
    if recipe.macros_protein_g:
        macro_bits.append(f"{recipe.macros_protein_g} g protein")
    if recipe.macros_carbs_g:
        macro_bits.append(f"{recipe.macros_carbs_g} g carbs")
    if recipe.macros_fat_g:
        macro_bits.append(f"{recipe.macros_fat_g} g fat")
    if getattr(recipe, "macros_fiber_g", None):
        macro_bits.append(f"{recipe.macros_fiber_g} g fiber")
    parts.extend(macro_bits)
    return " ".join(part for part in parts if part).strip()


def _recipe_has_ingredients(recipe: "Recipe", required_names: List[str]) -> bool:
    if not required_names:
        return True
    available = {
        (getattr(ing, "name", "") or "").strip().lower()
        for ing in getattr(recipe, "ingredients", []) or []
        if getattr(ing, "name", None)
    }
    if not available:
        return False
    return all(any(req == name for name in available) for req in required_names)


def _recipe_contains_terms(recipe: "Recipe", terms: List[str]) -> bool:
    """Return True if any of the provided terms appear in the recipe ingredients or document text."""
    if not terms:
        return False
    term_set = {t.strip().lower() for t in terms if t}
    if not term_set:
        return False

    # Check ingredient names
    for ing in getattr(recipe, "ingredients", []) or []:
        name = (getattr(ing, "name", "") or "").lower()
        if any(term in name for term in term_set):
            return True

    # Fall back to the flattened document representation
    doc_text = _recipe_document(recipe).lower()
    return any(term in doc_text for term in term_set)


def _build_query_text(req: "ComposeRequest", prefs: Prefs, constraints: Dict[str, Any]) -> str:
    bits = [
        req.message or "",
        f"servings {req.servings}",
    ]
    if req.preferences:
        bits.append(" ".join(req.preferences))
    pref_fields = prefs.model_dump(exclude_none=True)
    if pref_fields:
        bits.append(json.dumps(pref_fields, ensure_ascii=False))
    if constraints:
        bits.append(json.dumps({k: v for k, v in constraints.items() if v is not None}, ensure_ascii=False))
    return " ".join(bits)


def _recipe_matches_preferences(recipe: "Recipe", prefs: Prefs, constraints: Dict[str, Any]) -> bool:
    tags = [t.strip().lower() for t in (recipe.tags or "").split(",") if t.strip()]
    if prefs.vegan and "vegan" not in tags:
        return False
    if prefs.veggie and not any(t in tags for t in ("vegetarisch", "vegetarian", "veggie", "vegan")):
        return False
    if prefs.no_pork and any("pork" in t or "schwein" in t for t in tags):
        return False
    if prefs.cuisine_bias and tags:
        if not any(bias.lower() in tags for bias in prefs.cuisine_bias):
            return False
    max_kcal = constraints.get("max_kcal")
    if max_kcal is not None and recipe.macros_kcal is not None and recipe.macros_kcal > max_kcal:
        return False
    return True


def _recipes_matching_query(
    session: Session,
    req: "ComposeRequest",
    prefs: Prefs,
    constraints: Dict[str, Any],
    limit: int,
    required_ingredients: Optional[List[str]] = None,
) -> Tuple[List["RecipeIdea"], Dict[str, Any]]:
    """
    REFACTORED: Now uses modular RAG system (RecipeIndexer, QueryPreprocessor, PostProcessor).
    
    Behavior changes:
    - Recipe embeddings are cached in SQLite table (recipe_embeddings)
    - Document building and query preprocessing are handled by QueryPreprocessor
    - Scoring uses PostProcessor with configurable weights
    - Falls back to keyword matching if embeddings unavailable (same as before)
    """
    meta = {
        "reason": None,
        "used_embeddings": False,
        "candidates_total": 0,
        "candidates_filtered": 0,
    }
    if not HAS_RECIPES:
        meta["reason"] = "recipes_table_missing"
        return [], meta

    # Step 1: Retrieve candidate recipes from database
    stmt = (
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .order_by(Recipe.created_at.desc())
    )
    if RAG_MAX_RECIPES > 0:
        stmt = stmt.limit(RAG_MAX_RECIPES)
    recipes = session.exec(stmt).all()
    meta["candidates_total"] = len(recipes)

    # Step 2: Filter by preferences and required ingredients
    req_lower = [name.strip().lower() for name in (required_ingredients or []) if name]
    filtered: List[Recipe] = []
    for recipe in recipes:
        if not _recipe_matches_preferences(recipe, prefs, constraints):
            continue
        if req_lower and not _recipe_has_ingredients(recipe, req_lower):
            continue
        filtered.append(recipe)
    meta["candidates_filtered"] = len(filtered)

    if req_lower and not filtered:
        meta["reason"] = "required_ingredients_missing"
        meta["required_ingredients"] = req_lower
        return [], meta

    if not filtered:
        meta["reason"] = "no_recipe_matching_preferences"
        return [], meta

    # Step 3: Use modular RAG system if available, otherwise fallback to legacy code
    negative_ingredients = QueryPreprocessor.extract_negative_terms(req.message or "")
    if negative_ingredients:
        meta["negative_ingredients"] = negative_ingredients

    if RAG_MODULES_AVAILABLE:
        # Build query text using QueryPreprocessor
        prefs_dict = prefs.model_dump(exclude_none=True) if prefs else {}
        query_text = QueryPreprocessor.build_query_text(
            message=req.message or "",
            preferences=prefs_dict,
            constraints=constraints,
            servings=req.servings,
        )

        # Build document texts for recipes
        document_texts = [QueryPreprocessor.build_document(recipe) for recipe in filtered]

        # Initialize indexer with embedding client
        embedding_client = _embed_texts  # Use existing embedding function
        indexer = RecipeIndexer(session, embedding_client=embedding_client)

        # Get cached embeddings or compute new ones
        recipe_embeddings = indexer.batch_index(filtered, document_texts, force_refresh=False)

        # Embed query text
        query_vectors = embedding_client([query_text]) if embedding_client else None
        query_vec = query_vectors[0] if query_vectors and len(query_vectors) > 0 else None

        # Initialize post-processor with default weights
        post_processor = PostProcessor(
            semantic_weight=1.0,
            nutrition_weight=0.5,
            ingredient_weight=0.3,
        )

        # Determine if we should use embeddings or keyword fallback
        use_keyword_fallback = query_vec is None or not recipe_embeddings
        meta["used_embeddings"] = not use_keyword_fallback

        # Score recipes
        scored = post_processor.score_batch(
            recipes=filtered,
            query_vector=query_vec,
            recipe_vectors=recipe_embeddings if not use_keyword_fallback else None,
            query_text=query_text,
            constraints=constraints,
            use_keyword_fallback=use_keyword_fallback,
            negative_ingredients=negative_ingredients,
        )

        # Apply constraint filtering (already done above, but PostProcessor can do additional filtering)
        # Limit results
        scored = post_processor.rerank(scored, limit=limit)
    else:
        # Fallback to legacy implementation
        docs = [_recipe_document(recipe) for recipe in filtered]
        query_text = _build_query_text(req, prefs, constraints)

        vectors = _embed_texts([query_text] + docs) if docs else None
        scored: List[Tuple[float, Recipe]] = []

        if vectors and len(vectors) == len(docs) + 1:
            meta["used_embeddings"] = True
            query_vec = vectors[0]
            for recipe, doc_vec in zip(filtered, vectors[1:]):
                if negative_ingredients and _recipe_contains_terms(recipe, negative_ingredients):
                    continue
                score = _cosine(query_vec, doc_vec)
                score += _nutrition_fit_score(recipe, constraints)
                score += _ingredient_overlap_score(recipe, req.message or "")
                scored.append((score, recipe))
        else:
            if vectors and len(vectors) != len(docs) + 1:
                meta["reason"] = "embedding_size_mismatch"
            query_tokens = _tokenize(query_text)
            for recipe, doc_text in zip(filtered, docs):
                if negative_ingredients and _recipe_contains_terms(recipe, negative_ingredients):
                    continue
                doc_tokens = _tokenize(doc_text)
                score = _keyword_overlap(query_tokens, doc_tokens)
                score += _nutrition_fit_score(recipe, constraints)
                score += _ingredient_overlap_score(recipe, req.message or "")
                scored.append((score, recipe))
            if vectors is None:
                meta["reason"] = meta["reason"] or "embeddings_unavailable"

        scored.sort(key=lambda item: item[0], reverse=True)

    # Step 4: Convert scored recipes to RecipeIdea objects
    ideas: List[RecipeIdea] = []
    for score, recipe in scored[:limit]:
        idea = _recipe_to_idea(recipe)
        idea.source = "rag"
        if "rag" not in idea.tags:
            idea.tags.append("rag")
        idea = _tighten_with_foods_db(session, idea)
        idea = _respect_max_kcal(session, idea, constraints.get("max_kcal"))
        ideas.append(idea)

    if not ideas:
        meta["reason"] = meta["reason"] or "no_ranked_hits"
    elif len(ideas) < limit and meta["reason"] is None:
        meta["reason"] = "insufficient_hits"

    return ideas, meta

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
    intake_totals = _intake_for_day(session, day)
    intake = MacroTotals(
        kcal=float(round(intake_totals.kcal, 1)),
        protein_g=float(round(intake_totals.protein_g, 1)),
        carbs_g=float(round(intake_totals.carbs_g, 1)),
        fat_g=float(round(intake_totals.fat_g, 1)),
        fiber_g=float(round(getattr(intake_totals, "fiber_g", 0.0), 1)),
    )
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
            fiber_g=0.0,
        )
        notes.append(f"Ziel kcal via TDEE {round(base_kcal)} & Goal={goal} ({goal_mode}). Protein {protein_g_per_kg} g/kg.")

    remaining = None
    if target:
        remaining = MacroTotals(
            kcal=round(target.kcal - intake.kcal, 1),
            protein_g=round(target.protein_g - intake.protein_g, 1),
            carbs_g=round(target.carbs_g - intake.carbs_g, 1),
            fat_g=round(target.fat_g - intake.fat_g, 1),
            fiber_g=round(target.fiber_g - intake.fiber_g, 1),
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
    gaps_resp = gaps(day=day, body_weight_kg=body_weight_kg, goal=goal, protein_g_per_kg=protein_g_per_kg, session=session)
    if not gaps_resp.remaining:
        raise HTTPException(status_code=400, detail="Keine offenen Luecken - Ziel bereits erreicht.")
    remaining = gaps_resp.remaining

    prefs = Prefs(
        veggie=veggie,
        vegan=vegan,
        no_pork=no_pork,
        lactose_free=lactose_free,
        gluten_free=gluten_free,
        allergens_avoid=[s.strip() for s in allergens_avoid.split(",")] if allergens_avoid else None,
        budget_level=budget_level,
        cuisine_bias=[s.strip() for s in cuisine_bias.split(",")] if cuisine_bias else None,
    )

    suggestions: List[Suggestion] = []
    used_db = False
    used_llm = False
    used_fallback = False

    mock_req = ComposeRequest(
        message=f"Auto-Vorschlaege fuer {day}",
        day=day,
        body_weight_kg=body_weight_kg,
        servings=1,
        preferences=[],
    )
    library_constraints = {"max_kcal": remaining.kcal}
    library_ideas, _ = _recipes_matching_query(session, mock_req, prefs, library_constraints, limit=max_suggestions)
    if library_ideas:
        used_db = True
        suggestions = _merge_suggestions([], _ideas_to_suggestions(library_ideas, source="db"))

    def _fill_from_fallback(slots: int) -> None:
        nonlocal suggestions, used_fallback
        if slots <= 0:
            return
        fallback = _fallback_recommendations_from_foods(session, prefs, remaining, slots)
        if fallback:
            used_fallback = True
            suggestions = _merge_suggestions(suggestions, fallback)

    remaining_slots = max(0, max_suggestions - len(suggestions))

    if not SETTINGS.advisor_llm_enabled or mode == "db":
        _fill_from_fallback(remaining_slots)
        if not suggestions:
            raise HTTPException(status_code=503, detail="Keine Vorschlaege verfuegbar.")
        mode_used = "db"
        if used_fallback and used_db:
            mode_used = "hybrid"
        return RecommendationsResponse(day=day, remaining=remaining, mode=mode_used, suggestions=suggestions[:max_suggestions])

    foods_brief: List[Dict[str, Any]] = []
    rag_ctx: List[Dict[str, Any]] = []

    if mode in ("db", "hybrid", "rag"):
        foods = _apply_prefs_filter_foods(_food_list_for_prompt(session, top_n=48), prefs)
        foods_brief = [
            {
                "name": f.name,
                "kcal_100g": float(getattr(f, "kcal", 0) or 0),
                "protein_g_100g": float(getattr(f, "protein_g", 0) or 0),
                "carbs_g_100g": float(getattr(f, "carbs_g", 0) or 0),
                "fat_g_100g": float(getattr(f, "fat_g", 0) or 0),
            }
            for f in foods
        ]

    if mode in ("rag", "hybrid"):
        rag_ctx = _retrieve_candidates(session, prefs, top_k=RAG_TOP_K)

    remaining_json = json.dumps(remaining.model_dump(), ensure_ascii=False)
    prefs_json = json.dumps(prefs.model_dump(), ensure_ascii=False)

    base_instructions = (
        f"Erstelle {max_suggestions} alltagstaugliche Vorschlagskarten (1-3 Zutaten) in DE, "
        "um die Rest-Makros moeglichst gut zu treffen. "
        "Gib NUR JSON im Format:\n{\n  \"suggestions\": [\n    {\"name\":\"...\",\"items\":[{\"food\":\"...\",\"grams\":123}],\"est_kcal\":...,\"est_protein_g\":...,\"est_carbs_g\":...,\"est_fat_g\":...}\n  ]\n}"
        "Regeln: metrische Einheiten (g), realistische Mengen (50-400 g je Zutat), keine Erklaertexte ausserhalb JSON, "
        "Protein priorisieren bei Unterdeckung, Kalorienziel respektieren."
    )

    context_blocks: List[str] = []
    if rag_ctx:
        context_blocks.append("RAG_KANDIDATEN:\n" + json.dumps(rag_ctx, ensure_ascii=False))
    if foods_brief:
        context_blocks.append("FOODS_DB:\n" + json.dumps(foods_brief, ensure_ascii=False))

    context_str = "\n\n".join(context_blocks) if context_blocks else "KEIN_KONTEXT"
    prompt = (
        base_instructions
        + f"\n\nREMAINING:\n{remaining_json}\n\nPREFERENCES:\n{prefs_json}\n\nKONTEXT:\n{context_str}\n"
        + "Bevorzuge Kandidaten aus RAG_KANDIDATEN, verwende exakte Namen wenn vorhanden. "
        + "Fuelle Makros pragmatisch (keine ueberlangen Rezepte)."
    )

    llm_suggestions: List[Suggestion] = []
    try:
        raw = _ollama_generate(prompt, as_json=True)
        data = _parse_llm_json(raw)
        fb_names = {f["name"] for f in foods_brief} if foods_brief else set()
        rag_names = {c["name"] for c in rag_ctx} if rag_ctx else set()
        for entry in data.get("suggestions", []):
            items: List[SuggestionItem] = []
            for it in entry.get("items", []):
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
            if any(i.food in rag_names for i in items):
                origin = "rag"
            elif any(i.food in fb_names for i in items):
                origin = "db"
            else:
                origin = "llm"
            llm_suggestions.append(Suggestion(
                name=entry.get("name", "Vorschlag"),
                items=items,
                source=origin,
                est_kcal=entry.get("est_kcal"),
                est_protein_g=entry.get("est_protein_g"),
                est_carbs_g=entry.get("est_carbs_g"),
                est_fat_g=entry.get("est_fat_g"),
                est_fiber_g=entry.get("est_fiber_g"),
            ))
    except HTTPException:
        raise
    except Exception as exc:
        print("[WARN] Empfehlungen LLM fehlgeschlagen:", exc)

    if llm_suggestions:
        used_llm = True
        suggestions = _merge_suggestions(suggestions, llm_suggestions)

    remaining_slots = max(0, max_suggestions - len(suggestions))
    if remaining_slots > 0:
        _fill_from_fallback(remaining_slots)

    if not suggestions:
        raise HTTPException(status_code=502, detail="Keine verwertbaren Vorschlaege gefunden.")

    if used_llm and used_db:
        mode_used = "hybrid"
    elif used_llm:
        mode_used = "rag" if mode in ("rag", "hybrid") else "open"
    else:
        mode_used = "db"

    return RecommendationsResponse(day=day, remaining=remaining, mode=mode_used, suggestions=suggestions[:max_suggestions])
# ============ NEU: Chat-Endpunkt im Advisor (wie ChatGPT) ============

class ChatRequest(BaseModel):
    message: str = Field(..., description="Benutzereingabe (Frage/Aufgabe)")
    context: Optional[str] = Field(
        default=None,
        description="Optional: zusätzlicher Kontext (z.B. Tagesdaten, Ziele, Praeferenzen)."
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
    fiber_g: Optional[float] = None

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
    source: Literal["rag", "llm", "fallback", "db"] = "rag"

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
    kcal = p = c = f = fiber = 0.0
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
                fiber += (getattr(fobj, "fiber_g", 0.0) or 0.0) * factor
                hit = True
    if hit:
        idea.macros = Macro(
            kcal=round(kcal,1),
            protein_g=round(p,1),
            carbs_g=round(c,1),
            fat_g=round(f,1),
            fiber_g=round(fiber,1),
        )
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

    notes: List[str] = []
    ideas: List[RecipeIdea] = []
    required_ingredients = _infer_required_ingredients(session, req.message)
    if required_ingredients:
        notes.append("Filter: Zutaten " + ", ".join(required_ingredients))

    def _no_ideas_response(error: str, detail: str, status_code: int = 503) -> JSONResponse:
        payload = {"error": error, "detail": detail}
        if required_ingredients:
            payload["required_ingredients"] = required_ingredients
        code = 404 if required_ingredients else status_code
        return JSONResponse(status_code=code, content=payload)

    library_ideas, retrieval_meta = _recipes_matching_query(
        session,
        req,
        prefs,
        constraints,
        limit=3,
        required_ingredients=required_ingredients,
    )
    if library_ideas:
        notes.append(
            f"RAG fand {len(library_ideas)} passende Rezepte "
            f"(Kandidaten: {retrieval_meta.get('candidates_filtered', 0)})."
        )
        ideas = _merge_ideas(ideas, library_ideas)
    else:
        reason = retrieval_meta.get("reason") or "keine Übereinstimmungen"
        notes.append(f"RAG ohne Treffer: {reason}.")

    required_slots = max(0, 3 - len(ideas))
    if required_slots > 0:
        reason = retrieval_meta.get("reason") or "zu wenige Treffer"
        notes.append(f"{required_slots} weitere Idee(n) benötigt: {reason}.")
    llm_slots = 0 if required_ingredients else min(required_slots, 2)

    def _fill_from_fallback(slots: int) -> None:
        if required_ingredients or slots <= 0:
            return
        fallback = _compose_fallback_ideas(session, req, constraints, prefs)[:slots]
        if fallback:
            notes.append("Fallback-Vorschlaege aus lokalen Lebensmitteln.")
            _persist_recipe_ideas(session, req, prefs, constraints, fallback, source="fallback")
            nonlocal ideas, required_slots
            for idea in fallback:
                idea.source = "fallback"
            ideas = _merge_ideas(ideas, fallback)
            required_slots = max(0, 3 - len(ideas))

    if not SETTINGS.advisor_llm_enabled or llm_slots == 0:
        if required_slots > 0:
            _fill_from_fallback(required_slots)
        if not ideas:
            return _no_ideas_response("no_ideas", "Keine passenden Rezepte gefunden.")
        return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

    has_local_llm = bool(LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(LLAMA_CPP_MODEL_PATH))
    if not has_local_llm and not _ollama_alive(timeout=2):
        notes.append("LLM nicht erreichbar - lokale Fallbacks aktiv.")
        if required_slots > 0:
            _fill_from_fallback(required_slots)
        if not ideas:
            payload = {
                "error": "llm_unavailable",
                "detail": "Kein lokales LLM erreichbar und keine lokalen Rezept-Heuristiken verfuegbar. Bitte Ollama starten oder Food-Datenbank befuellen.",
            }
            if required_ingredients:
                payload["required_ingredients"] = required_ingredients
            code = 404 if required_ingredients else 503
            return JSONResponse(status_code=code, content=payload)
        return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

    system = (
        "Du bist ein praeziser deutschsprachiger Ernaehrungscoach. "
        f"Liefere exakt {llm_slots} praktische Rezeptidee(n) mit Zutaten (in g), klaren Schritten und geschaetzten Makros pro Portion. "
        "Beachte Praeferenzen (vegetarian/vegan/no_pork/lactose_free/budget/kitchen=italian,german,...). "
        "Antworte ausschliesslich als JSON in dem angegebenen Format."
    )
    prefs_payload = prefs.model_dump(exclude_none=True)
    preferences_str = json.dumps(prefs_payload, ensure_ascii=False) if prefs_payload else "keine"
    constraints_str = json.dumps(constraints, ensure_ascii=False)
    user_template = """
Nutzeranfrage: {message}
Servings: {servings}
Praeferenzen: {preferences}
Constraints: {constraints}
JSON-Format:
{{
  \"ideas\": [
    {{
      \"title\": \"...\",
      \"time_minutes\": 20,
      \"difficulty\": \"easy\",
      \"ingredients\": [{{\"name\":\"...\", \"grams\":120}}, ...],
      \"instructions\": [\"Schritt 1 ...\",\"Schritt 2 ...\"],
      \"macros\": {{\"kcal\": ..., \"protein_g\": ..., \"carbs_g\": ..., \"fat_g\": ...}},
      \"tags\": [\"proteinreich\",\"unter_800_kcal\"]
    }},
    ...
  ]
}}
Regeln: metrisch, 50-400 g/Zutat, pro Portion <= max_kcal falls gesetzt. Keine Erklaertexte ausserhalb des JSON.
"""
    user = user_template.format(
        message=req.message,
        servings=req.servings,
        preferences=preferences_str,
        constraints=constraints_str,
    )
    try:
        from app.utils.llm import llm_generate_json
        raw_ideas = llm_generate_json(
            system,
            user,
            model=OLLAMA_MODEL,
            endpoint=f"http://{OLLAMA_HOST}:{OLLAMA_PORT}",
            json_root="ideas",
        )
    except Exception:
        raw = _ollama_generate(f"{system}\n\n{user}", as_json=True, timeout=OLLAMA_TIMEOUT)
        data = _parse_llm_json(raw)
        raw_ideas = data.get("ideas", [])

        if not isinstance(raw_ideas, list):
            raise ValueError("LLM lieferte kein ideas-Array.")
    except HTTPException:
        raise
    except Exception as exc:
        notes.append(f"LLM-Fehler: {exc}")
        if required_slots > 0:
            _fill_from_fallback(required_slots)
        return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

    llm_ideas: List[RecipeIdea] = []
    try:
        from app.utils.validators import clamp, safe_float
    except Exception:
        clamp = lambda x, lo, hi: max(lo, min(hi, x))
        def safe_float(x):
            try:
                return float(x)
            except Exception:
                return 0.0

    raw_ideas = list(raw_ideas or [])[:llm_slots]
    for idea_dict in raw_ideas:
        try:
            idea = RecipeIdea(**idea_dict)
        except Exception:
            continue
        if idea.macros:
            idea.macros.kcal = clamp(safe_float(idea.macros.kcal), 0, 1400)
            idea.macros.protein_g = clamp(safe_float(idea.macros.protein_g), 0, 200)
            idea.macros.carbs_g = clamp(safe_float(idea.macros.carbs_g), 0, 250)
            idea.macros.fat_g = clamp(safe_float(idea.macros.fat_g), 0, 120)
            if idea.macros.fiber_g is not None:
                idea.macros.fiber_g = clamp(safe_float(idea.macros.fiber_g), 0, 80)
        idea.source = "llm"
        if "llm" not in idea.tags:
            idea.tags.append("llm")
        idea = _tighten_with_foods_db(session, idea)
        llm_ideas.append(idea)

    if llm_ideas:
        notes.append("Ergaenzung durch lokales LLM.")
        _persist_recipe_ideas(session, req, prefs, constraints, llm_ideas, source="llm")
        ideas = _merge_ideas(ideas, llm_ideas)
        required_slots = max(0, 3 - len(ideas))

    if len(ideas) < 3:
        _fill_from_fallback(required_slots)

    if not ideas:
        return _no_ideas_response("no_ideas", "Keine verwertbaren Ideen generiert.", status_code=502)

    if constraints.get("max_kcal"):
        over = [i.title for i in ideas if i.macros and i.macros.kcal > constraints["max_kcal"]]
        if over:
            notes.append(f"Ideen > max_kcal ({constraints['max_kcal']}): {', '.join(over)}")

    return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

