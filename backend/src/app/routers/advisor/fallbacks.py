from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from sqlmodel import Session, select

from app.models.foods import Food

from .helpers import (
    _apply_prefs_filter_foods,
    _combo_matches_preferences,
    _combo_score,
    _fallback_instructions,
    _fallback_title,
    _food_list_for_prompt,
    _macros_from_food,
    _respect_max_kcal,
    _tighten_with_foods_db,
)
from .schemas import (
    ComposeRequest,
    Ingredient,
    Prefs,
    RecipeIdea,
    Suggestion,
    SuggestionItem,
)


def _fallback_recommendations_from_foods(
    session: Session,
    prefs: Prefs,
    remaining,
    limit: int,
) -> List[Suggestion]:
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
                macro_primary.fiber_g += macro_side.fiber_g
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


def _generic_fallback_ideas(req: ComposeRequest, prefs: Prefs) -> List[RecipeIdea]:
    message_hint = (req.message or "").lower()

    combos: List[Dict[str, Any]] = [
        {
            "title": "Tofu-Gemuese-Pfanne",
            "ingredients": [
                ("Tofu natur", 200.0),
                ("Brokkoli", 120.0),
                ("Paprika", 80.0),
                ("Sesamoel", 10.0),
            ],
            "instructions": [
                "Tofu in Wuerfel schneiden und in etwas Oel knusprig anbraten.",
                "Gemuese zugeben, wuerzen und bissfest garen.",
            ],
            "tags": ["vegan", "warm", "pfanne", "asian"],
            "kind": "dinner",
            "diet": "vegan",
            "cost": "low",
        },
        {
            "title": "Kichererbsen-Quinoa-Bowl",
            "ingredients": [
                ("Kichererbsen (Dose)", 160.0),
                ("Quinoa gekocht", 140.0),
                ("Gurkenwuerfel", 80.0),
                ("Babyspinat", 50.0),
                ("Olivenoel", 12.0),
            ],
            "instructions": [
                "Quinoa nach Packungsangabe garen.",
                "Kichererbsen abspuelen, mit Gemuese und Spinat mischen, mit Oel und Zitrone abschmecken.",
            ],
            "tags": ["vegan", "bowl", "mediterran"],
            "kind": "lunch",
            "diet": "vegan",
            "cost": "low",
        },
        {
            "title": "Hafer-Beeren-Fruehstueck",
            "ingredients": [
                ("Haferflocken", 60.0),
                ("Pflanzendrink", 200.0),
                ("Beerenmischung", 120.0),
                ("Mandeln gehackt", 20.0),
            ],
            "instructions": [
                "Haferflocken mit Pflanzendrink kurz erhitzen oder ueber Nacht einweichen.",
                "Mit Beeren und Mandeln toppen.",
            ],
            "tags": ["fruehstueck", "vegetarisch", "bowl"],
            "kind": "breakfast",
            "diet": "vegetarian",
            "cost": "low",
        },
        {
            "title": "Huehnchen mit Ofengemuese",
            "ingredients": [
                ("Huhnbrustfilet", 180.0),
                ("Suesse Kartoffel", 150.0),
                ("Zucchini", 120.0),
                ("Olivenoel", 12.0),
            ],
            "instructions": [
                "Gemuese wuerfeln, mit Oel und Gewuerzen vermengen und im Ofen roesten.",
                "Huehnchen wuerzen und mit backen oder separat anbraten.",
            ],
            "tags": ["warm", "deftig", "german"],
            "kind": "dinner",
            "diet": "omnivore",
            "cost": "mid",
        },
        {
            "title": "Linsen-Nudel-Salat",
            "ingredients": [
                ("Linsennudeln gekocht", 150.0),
                ("Cherrytomaten", 100.0),
                ("Rucola", 40.0),
                ("Feta (optional)", 40.0),
                ("Olivenoel", 12.0),
            ],
            "instructions": [
                "Nudeln kochen, kalt abschrecken.",
                "Mit Tomaten, Rucola und Dressing vermischen, optional Feta dazugeben.",
            ],
            "tags": ["lunch", "bowl", "mediterran"],
            "kind": "lunch",
            "diet": "vegetarian",
            "cost": "low",
        },
        {
            "title": "Avocado-Vollkorn-Toast",
            "ingredients": [
                ("Vollkorntoast", 70.0),
                ("Avocado", 80.0),
                ("Cherrytomaten", 60.0),
                ("Kresse", 5.0),
                ("Zitronensaft", 10.0),
            ],
            "instructions": [
                "Toast roesten, Avocado zerdruecken und mit Zitronensaft, Salz und Pfeffer abschmecken.",
                "Auf Toast streichen, mit Tomaten und Kresse belegen.",
            ],
            "tags": ["snack", "vegetarisch"],
            "kind": "snack",
            "diet": "vegetarian",
            "cost": "mid",
        },
    ]

    ingredient_templates: List[List[Ingredient]] = [
        [Ingredient(name=name, grams=grams) for name, grams in combo["ingredients"]]
        for combo in combos
    ]

    available_combos: List[Dict[str, Any]] = []
    for combo, ingredients in zip(combos, ingredient_templates):
        if _combo_matches_preferences(ingredients, prefs):
            combo_copy = dict(combo)
            combo_copy["ingredients_obj"] = ingredients
            available_combos.append(combo_copy)

    if not available_combos:
        for combo, ingredients in zip(combos, ingredient_templates):
            filtered: List[Ingredient] = []
            for ingredient in ingredients:
                if prefs.vegan and any(
                    token in ingredient.name.lower()
                    for token in ["huhn", "feta", "skyr", "huhnbrust", "huehn"]
                ):
                    continue
                if prefs.lactose_free and "feta" in ingredient.name.lower():
                    continue
                filtered.append(ingredient)
            combo_copy = dict(combo)
            combo_copy["ingredients_obj"] = filtered or ingredients
            available_combos.append(combo_copy)

    available_combos.sort(
        key=lambda combo: _combo_score(combo, message_hint, prefs), reverse=True
    )

    ideas: List[RecipeIdea] = []
    for combo in available_combos:
        ingredients = [
            Ingredient(name=ingredient.name, grams=ingredient.grams)
            for ingredient in combo["ingredients_obj"]
        ]
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
            candidate = foods_pool[(idx + offset) % len(foods_pool)]
            if candidate is main or candidate in sides:
                continue
            sides.append(candidate)
            if len(sides) >= 2:
                break

        main_protein = float(getattr(main, "protein_g", 0.0) or 0.0)
        main_grams = 180.0 if main_protein >= 20.0 else 200.0
        ingredients = [
            Ingredient(name=getattr(main, "name", "Hauptzutat"), grams=round(main_grams, 1))
        ]

        for side in sides:
            carbs = float(getattr(side, "carbs_g", 0.0) or 0.0)
            protein = float(getattr(side, "protein_g", 0.0) or 0.0)
            grams = 120.0 if carbs >= protein else 90.0
            ingredients.append(
                Ingredient(name=getattr(side, "name", "Beilage"), grams=round(grams, 1))
            )

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

