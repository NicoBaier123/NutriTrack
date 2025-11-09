from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlmodel import Session, select

from app.models.foods import Food

from .config import RAG_EMBED_URL
from .schemas import Ingredient, Macro, MacroTotals, Prefs, RecipeIdea

try:  # pragma: no cover - optional dependency
    from app.models.recipes import Recipe  # noqa: F401
except Exception:  # pragma: no cover - optional dependency
    Recipe = None  # type: ignore


def _food_list_for_prompt(session: Session, top_n: int = 24) -> List[Food]:
    foods = session.exec(select(Food)).all()

    def score(food: Food) -> float:
        kcal = getattr(food, "kcal", 0) or 0
        if kcal <= 0:
            return 0.0
        protein = getattr(food, "protein_g", 0) or 0
        return (protein / kcal) * 100.0

    foods_sorted = sorted(foods, key=score, reverse=True)
    return foods_sorted[:top_n]


def _macros_from_food(food: Food, grams: float) -> MacroTotals:
    factor = grams / 100.0
    return MacroTotals(
        kcal=float((getattr(food, "kcal", 0) or 0) * factor),
        protein_g=float((getattr(food, "protein_g", 0) or 0) * factor),
        carbs_g=float((getattr(food, "carbs_g", 0) or 0) * factor),
        fat_g=float((getattr(food, "fat_g", 0) or 0) * factor),
        fiber_g=float((getattr(food, "fiber_g", 0) or 0) * factor),
    )


def _mk_goal_kcal(
    base_kcal: float,
    goal: str,
    goal_mode: str,
    percent: float,
    offset_kcal: float,
    rate_kg_per_week: float,
) -> float:
    if goal == "maintain":
        return base_kcal

    if goal_mode == "percent":
        add = base_kcal * (abs(percent) / 100.0)
    elif goal_mode == "kcal":
        add = abs(offset_kcal)
    else:
        add = abs(rate_kg_per_week) * 7700.0 / 7.0
    return base_kcal + (add if goal == "bulk" else -add)


def _apply_prefs_filter_foods(foods: Sequence[Food], prefs: Prefs) -> List[Food]:
    result: List[Food] = []
    for food in foods:
        name = (getattr(food, "name", "") or "").lower()
        if not name:
            continue
        if prefs.vegan and any(
            token in name
            for token in ["quark", "joghurt", "käse", "kaese", "milch", "hähnchen", "pute", "fisch", "ei"]
        ):
            continue
        if prefs.veggie and any(
            token in name for token in ["hähnchen", "pute", "rind", "schwein", "fisch", "thunfisch", "lachs"]
        ):
            continue
        if prefs.no_pork and "schwein" in name:
            continue
        if (
            prefs.lactose_free
            and any(token in name for token in ["milch", "joghurt", "quark", "käse", "kaese"])
            and "laktosefrei" not in name
        ):
            continue
        if prefs.allergens_avoid and any(
            allergen.lower() in name for allergen in (prefs.allergens_avoid or [])
        ):
            continue
        result.append(food)
    return result


def _embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    if not RAG_EMBED_URL:
        return None

    try:
        import urllib.request

        payload = json.dumps({"texts": texts}).encode("utf-8")
        req = urllib.request.Request(
            RAG_EMBED_URL, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read()).get("vectors")
    except Exception:
        return None


def _cosine(a: Iterable[float], b: Iterable[float]) -> float:
    a_list = list(a)
    b_list = list(b)
    num = sum(x * y for x, y in zip(a_list, b_list))
    da = math.sqrt(sum(x * x for x in a_list))
    db = math.sqrt(sum(y * y for y in b_list))
    return num / (da * db + 1e-9)


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

    try:
        from app.rag.preprocess import QueryPreprocessor

        negative_terms = set(QueryPreprocessor.extract_negative_terms(message))
    except Exception:
        negative_terms = set()
    negative_tokens = {tok for term in negative_terms for tok in _tokenize(term)}

    names = session.exec(select(Food.name)).all()
    matches: List[str] = []
    seen: set[str] = set()
    for raw_name in names:
        name = (raw_name or "").strip()
        if not name:
            continue
        name_tokens = set(_tokenize(name))
        if not name_tokens:
            continue
        if negative_tokens and name_tokens & negative_tokens:
            continue
        if not name_tokens <= message_tokens:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        matches.append(name)
    return matches


def _tighten_with_foods_db(session: Session, idea: RecipeIdea) -> RecipeIdea:
    kcal = protein = carbs = fat = fiber = 0.0
    hit = False
    for ingredient in idea.ingredients:
        if ingredient.grams and ingredient.grams > 0:
            food_obj = session.exec(
                select(Food).where(Food.name == ingredient.name)
            ).first()
            if food_obj:
                factor = ingredient.grams / 100.0
                kcal += (food_obj.kcal or 0.0) * factor
                protein += (food_obj.protein_g or 0.0) * factor
                carbs += (food_obj.carbs_g or 0.0) * factor
                fat += (food_obj.fat_g or 0.0) * factor
                fiber += (getattr(food_obj, "fiber_g", 0.0) or 0.0) * factor
                hit = True
    if hit:
        idea.macros = Macro(
            kcal=round(kcal, 1),
            protein_g=round(protein, 1),
            carbs_g=round(carbs, 1),
            fat_g=round(fat, 1),
            fiber_g=round(fiber, 1),
        )
    return idea


def _respect_max_kcal(
    session: Session, idea: RecipeIdea, max_kcal: Optional[float]
) -> RecipeIdea:
    if not max_kcal or not idea.macros or idea.macros.kcal <= max_kcal:
        return idea
    if idea.macros.kcal <= 0:
        return idea

    scale = max(max_kcal / idea.macros.kcal, 0.4)
    changed = False
    for ingredient in idea.ingredients:
        if ingredient.grams and ingredient.grams > 0:
            ingredient.grams = round(max(40.0, ingredient.grams * scale), 1)
            changed = True
    if changed:
        idea = _tighten_with_foods_db(session, idea)
    return idea


def _prefs_from_compose(req_preferences: Sequence[str]) -> Prefs:
    pref_set = set(req_preferences or [])
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
    return f"Idee {idx + 1}: {name}"


def _fallback_instructions(main_food: Food, sides: Sequence[Food]) -> List[str]:
    steps = [
        f"{getattr(main_food, 'name', 'Hauptzutat')} portionsgerecht zubereiten (anbraten, backen oder daempfen)."
    ]
    if sides:
        steps.append("Beilagen garen oder frisch anrichten und nach Bedarf wuerzen.")
    steps.append("Alles zusammen anrichten, abschmecken und servieren.")
    return steps


def _combo_matches_preferences(ingredients: Sequence[Ingredient], prefs: Prefs) -> bool:
    def _name_has(substrs: Sequence[str], name: str) -> bool:
        lower = name.lower()
        return any(sub in lower for sub in substrs)

    if prefs.vegan:
        for ingredient in ingredients:
            if _name_has(
                [
                    "huhn",
                    "puten",
                    "rind",
                    "lachs",
                    "fisch",
                    "ei",
                    "joghurt",
                    "skyr",
                    "kaese",
                    "käse",
                    "quark",
                ],
                ingredient.name,
            ):
                return False
    elif prefs.veggie:
        for ingredient in ingredients:
            if _name_has(
                ["huhn", "puten", "rind", "lachs", "schinken", "speck", "fisch"],
                ingredient.name,
            ):
                return False

    if prefs.no_pork:
        for ingredient in ingredients:
            if _name_has(["schwein", "schinken", "speck"], ingredient.name):
                return False

    if prefs.lactose_free:
        for ingredient in ingredients:
            if _name_has(
                ["milch", "joghurt", "skyr", "kaese", "käse", "quark", "butter"],
                ingredient.name,
            ) and "laktosefrei" not in ingredient.name.lower():
                return False
    return True


def _combo_score(meta: Dict[str, Any], message_hint: str, prefs: Prefs) -> float:
    score = 0.0
    kind = meta.get("kind")
    tags = meta.get("tags", [])
    hint = message_hint

    if kind == "breakfast" and any(token in hint for token in ["frueh", "breakfast", "morg"]):
        score += 3.0
    if kind == "snack" and "snack" in hint:
        score += 2.5
    if kind in ("lunch", "dinner") and any(
        token in hint for token in ["mittag", "lunch", "abend", "dinner"]
    ):
        score += 2.5

    if prefs.cuisine_bias:
        if any(tag in prefs.cuisine_bias for tag in tags):
            score += 1.5
        else:
            score -= 0.5

    if prefs.budget_level == "low" and meta.get("cost") == "low":
        score += 0.5

    if "bowl" in hint and "bowl" in tags:
        score += 1.0
    return score

