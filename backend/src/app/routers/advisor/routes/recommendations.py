from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.database import get_session

from ..config import RAG_TOP_K, SETTINGS
from ..fallbacks import _fallback_recommendations_from_foods
from ..helpers import _apply_prefs_filter_foods, _food_list_for_prompt
from ..llm import _ollama_generate, _parse_llm_json
from ..rag import (
    _ideas_to_suggestions,
    _merge_suggestions,
    _recipes_matching_query,
    _retrieve_candidates,
)
from ..schemas import (
    ComposeRequest,
    Prefs,
    RecommendationsResponse,
    Suggestion,
    SuggestionItem,
)
from .gaps import gaps

router = APIRouter()


@router.get("/recommendations", response_model=RecommendationsResponse)
def recommendations(
    day: date = Query(...),
    body_weight_kg: float = Query(..., ge=0.0),
    goal: str = Query("maintain"),
    protein_g_per_kg: float = Query(1.8, ge=1.2, le=2.4),
    max_suggestions: int = Query(4, ge=1, le=8),
    mode: Literal["db", "open", "rag", "hybrid"] = Query("rag"),
    veggie: Optional[bool] = None,
    vegan: Optional[bool] = None,
    no_pork: Optional[bool] = None,
    lactose_free: Optional[bool] = None,
    gluten_free: Optional[bool] = None,
    allergens_avoid: Optional[str] = Query(None, description="Komma-getrennt"),
    budget_level: Optional[Literal["low", "mid", "high"]] = None,
    cuisine_bias: Optional[str] = Query(
        None, description="Komma-getrennt, z.B. de,med,asian"
    ),
    session: Session = Depends(get_session),
):
    gaps_resp = gaps(
        day=day,
        body_weight_kg=body_weight_kg,
        goal=goal,
        protein_g_per_kg=protein_g_per_kg,
        session=session,
    )
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
    library_ideas, _ = _recipes_matching_query(
        session, mock_req, prefs, library_constraints, limit=max_suggestions
    )
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
        return RecommendationsResponse(
            day=day, remaining=remaining, mode=mode_used, suggestions=suggestions[:max_suggestions]
        )

    foods_brief: List[Dict[str, Any]] = []
    rag_ctx: List[Dict[str, Any]] = []

    if mode in ("db", "hybrid", "rag"):
        foods = _apply_prefs_filter_foods(_food_list_for_prompt(session, top_n=48), prefs)
        foods_brief = [
            {
                "name": food.name,
                "kcal_100g": float(getattr(food, "kcal", 0) or 0),
                "protein_g_100g": float(getattr(food, "protein_g", 0) or 0),
                "carbs_g_100g": float(getattr(food, "carbs_g", 0) or 0),
                "fat_g_100g": float(getattr(food, "fat_g", 0) or 0),
            }
            for food in foods
        ]

    if mode in ("rag", "hybrid"):
        rag_ctx = _retrieve_candidates(session, prefs, top_k=RAG_TOP_K or len(foods_brief) or 10)

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
        fb_names = {entry["name"] for entry in foods_brief} if foods_brief else set()
        rag_names = {candidate["name"] for candidate in rag_ctx} if rag_ctx else set()
        for entry in data.get("suggestions", []):
            items: List[SuggestionItem] = []
            for raw_item in entry.get("items", []):
                try:
                    food_name = (raw_item.get("food") or "").strip()
                    grams = float(raw_item.get("grams", 0))
                except Exception:
                    continue
                if not food_name or grams <= 0:
                    continue
                items.append(SuggestionItem(food=food_name, grams=grams))
            if not items:
                continue
            if any(item.food in rag_names for item in items):
                origin = "rag"
            elif any(item.food in fb_names for item in items):
                origin = "db"
            else:
                origin = "llm"
            llm_suggestions.append(
                Suggestion(
                    name=entry.get("name", "Vorschlag"),
                    items=items,
                    source=origin,
                    est_kcal=entry.get("est_kcal"),
                    est_protein_g=entry.get("est_protein_g"),
                    est_carbs_g=entry.get("est_carbs_g"),
                    est_fat_g=entry.get("est_fat_g"),
                    est_fiber_g=entry.get("est_fiber_g"),
                )
            )
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

    return RecommendationsResponse(
        day=day, remaining=remaining, mode=mode_used, suggestions=suggestions[:max_suggestions]
    )
