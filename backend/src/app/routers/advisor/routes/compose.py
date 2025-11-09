from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.core.database import get_session
from app.routers.summary import (
    _active_minutes_for_day,
    _intake_for_day,
    _target_kcal_for_day,
)

from ..config import LLAMA_CPP_MODEL_PATH, OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_PORT, OLLAMA_TIMEOUT, SETTINGS
from ..fallbacks import _compose_fallback_ideas
from ..helpers import (
    _infer_required_ingredients,
    _prefs_from_compose,
    _respect_max_kcal,
    _tighten_with_foods_db,
)
from ..llm import (
    LLAMA_CPP_AVAILABLE,
    _ollama_alive,
    _ollama_generate,
    _parse_llm_json,
)
from ..rag import (
    _merge_ideas,
    _persist_recipe_ideas,
    _recipes_matching_query,
)
from ..schemas import (
    ComposeRequest,
    ComposeResponse,
    Prefs,
    RecipeIdea,
)

router = APIRouter()


def _constraints_from_context(session: Session, req: ComposeRequest) -> Dict[str, Any]:
    constraints: Dict[str, Any] = {"max_kcal": None, "protein_bias": False}
    if req.day and req.body_weight_kg:
        intake = _intake_for_day(session, req.day)
        actmin = _active_minutes_for_day(session, req.day)
        target = _target_kcal_for_day(req.body_weight_kg, actmin) or 0.0
        remaining = target - intake.kcal
        protein_target = 2.0 * req.body_weight_kg
        constraints.update(
            {
                "target_kcal": round(target, 0),
                "remaining_kcal": round(remaining, 0),
                "protein_target_g": round(protein_target, 0),
            }
        )
        constraints["protein_bias"] = (protein_target - intake.protein_g) > 25
        constraints["max_kcal"] = max(400, min(900, remaining + 200)) if remaining > 0 else 650
    return constraints


def _fill_pref_tags(idea: RecipeIdea, prefs: Prefs) -> RecipeIdea:
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
    return idea


@router.post("/compose", response_model=ComposeResponse)
def compose(req: ComposeRequest, session: Session = Depends(get_session)):
    constraints = _constraints_from_context(session, req)
    prefs = _prefs_from_compose(req.preferences)

    notes: List[str] = []
    ideas: List[RecipeIdea] = []
    required_ingredients = _infer_required_ingredients(session, req.message)
    if required_ingredients:
        notes.append("Filter: Zutaten " + ", ".join(required_ingredients))

    def _no_ideas_response(error: str, detail: str, status_code: int = 503) -> JSONResponse:
        payload: Dict[str, Any] = {"error": error, "detail": detail}
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
        nonlocal ideas, required_slots
        if required_ingredients or slots <= 0:
            return
        fallback = _compose_fallback_ideas(session, req, constraints, prefs)[:slots]
        if fallback:
            notes.append("Fallback-Vorschlaege aus lokalen Lebensmitteln.")
            _persist_recipe_ideas(session, req, prefs, constraints, fallback, source="fallback")
            for idea in fallback:
                idea.source = "fallback"
                _fill_pref_tags(idea, prefs)
            ideas = _merge_ideas(ideas, fallback)
            required_slots = max(0, 3 - len(ideas))

    if not SETTINGS.advisor_llm_enabled or llm_slots == 0:
        if required_slots > 0:
            _fill_from_fallback(required_slots)
        if not ideas:
            return _no_ideas_response("no_ideas", "Keine passenden Rezepte gefunden.")
        return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

    has_local_llm = bool(
        LLAMA_CPP_AVAILABLE and LLAMA_CPP_MODEL_PATH and os.path.exists(LLAMA_CPP_MODEL_PATH)
    )
    if not has_local_llm and not _ollama_alive(timeout=2):
        notes.append("LLM nicht erreichbar - lokale Fallbacks aktiv.")
        if required_slots > 0:
            _fill_from_fallback(required_slots)
        if not ideas:
            payload: Dict[str, Any] = {
                "error": "llm_unavailable",
                "detail": "Kein lokales LLM erreichbar und keine lokalen Rezept-Heuristiken verfuegbar. Bitte Ollama starten oder Food-Datenbank befuellen.",
            }
            if required_ingredients:
                payload["required_ingredients"] = required_ingredients
            code = 404 if required_ingredients else 503
            return JSONResponse(status_code=code, content=payload)
        return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

    system_prompt = (
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
    user_prompt = user_template.format(
        message=req.message,
        servings=req.servings,
        preferences=preferences_str,
        constraints=constraints_str,
    )

    try:
        from app.utils.llm import llm_generate_json

        raw_ideas = llm_generate_json(
            system_prompt,
            user_prompt,
            model=OLLAMA_MODEL,
            endpoint=f"http://{OLLAMA_HOST}:{OLLAMA_PORT}",
            json_root="ideas",
        )
    except Exception:
        raw = _ollama_generate(f"{system_prompt}\n\n{user_prompt}", as_json=True, timeout=OLLAMA_TIMEOUT)
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
        clamp = lambda value, lo, hi: max(lo, min(hi, value))  # type: ignore[assignment]

        def safe_float(value):  # type: ignore[no-redef]
            try:
                return float(value)
            except Exception:
                return 0.0

    raw_ideas = list(raw_ideas or [])[:llm_slots]
    for idea_dict in raw_ideas:
        try:
            idea = RecipeIdea(**idea_dict)
        except Exception:
            continue
        if idea.macros:
            idea.macros.kcal = clamp(safe_float(idea.macros.kcal), 0, 1400)  # type: ignore[arg-type]
            idea.macros.protein_g = clamp(safe_float(idea.macros.protein_g), 0, 200)
            idea.macros.carbs_g = clamp(safe_float(idea.macros.carbs_g), 0, 250)
            idea.macros.fat_g = clamp(safe_float(idea.macros.fat_g), 0, 120)
            if idea.macros.fiber_g is not None:
                idea.macros.fiber_g = clamp(safe_float(idea.macros.fiber_g), 0, 80)
        idea.source = "llm"
        if "llm" not in idea.tags:
            idea.tags.append("llm")
        idea = _tighten_with_foods_db(session, idea)
        idea = _fill_pref_tags(idea, prefs)
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
        over_limit = [
            idea.title for idea in ideas if idea.macros and idea.macros.kcal > constraints["max_kcal"]
        ]
        if over_limit:
            notes.append(f"Ideen > max_kcal ({constraints['max_kcal']}): {', '.join(over_limit)}")

    ideas = [_fill_pref_tags(_respect_max_kcal(session, idea, constraints.get("max_kcal")), prefs) for idea in ideas]

    return ComposeResponse(constraints=constraints, ideas=ideas[:3], notes=notes)

