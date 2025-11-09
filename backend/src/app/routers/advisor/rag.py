from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.models.foods import Food

from .config import HAS_RECIPES, RAG_MAX_RECIPES, RAG_TOP_K, Recipe, RecipeItem
from .helpers import (
    _apply_prefs_filter_foods,
    _cosine,
    _embed_texts,
    _respect_max_kcal,
    _tighten_with_foods_db,
    _tokenize,
)
from .schemas import (
    ComposeRequest,
    Ingredient,
    Macro,
    Prefs,
    RecipeIdea,
    Suggestion,
)

try:  # pragma: no cover - optional dependency
    from app.rag.indexer import RecipeIndexer, RecipeEmbedding  # noqa: F401
    from app.rag.preprocess import QueryPreprocessor
    from app.rag.postprocess import PostProcessor

    RAG_MODULES_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency
    RecipeIndexer = None  # type: ignore
    QueryPreprocessor = None  # type: ignore
    PostProcessor = None  # type: ignore
    RAG_MODULES_AVAILABLE = False


def _keyword_overlap(query_tokens: Iterable[str], doc_tokens: Iterable[str]) -> float:
    qs = set(query_tokens)
    ds = set(doc_tokens)
    if not qs or not ds:
        return 0.0
    return len(qs & ds) / max(len(qs), 1)


def _recipe_contains_terms(recipe: "Recipe", terms: List[str]) -> bool:
    if not terms:
        return False
    term_set = {term.strip().lower() for term in terms if term}
    if not term_set:
        return False

    for ingredient in getattr(recipe, "ingredients", []) or []:
        name = (getattr(ingredient, "name", "") or "").lower()
        if any(term in name for term in term_set):
            return True

    doc_text = _recipe_document(recipe).lower()
    return any(term in doc_text for term in term_set)


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
    for ingredient in getattr(recipe, "ingredients", []) or []:
        parts.append(f"{ingredient.name} {ingredient.grams or ''}".strip())
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
        (getattr(ingredient, "name", "") or "").strip().lower()
        for ingredient in getattr(recipe, "ingredients", []) or []
        if getattr(ingredient, "name", None)
    }
    if not available:
        return False
    return all(any(req == name for name in available) for req in required_names)


def _recipe_matches_preferences(recipe: "Recipe", prefs: Prefs, constraints: Dict[str, Any]) -> bool:
    tags = [t.strip().lower() for t in (recipe.tags or "").split(",") if t.strip()]
    if prefs.vegan and "vegan" not in tags:
        return False
    if prefs.veggie and not any(
        tag in tags for tag in ("vegetarisch", "vegetarian", "veggie", "vegan")
    ):
        return False
    if prefs.no_pork and any("pork" in tag or "schwein" in tag for tag in tags):
        return False
    if prefs.cuisine_bias and tags:
        if not any(bias.lower() in tags for bias in prefs.cuisine_bias):
            return False
    max_kcal = constraints.get("max_kcal")
    if max_kcal is not None and recipe.macros_kcal is not None and recipe.macros_kcal > max_kcal:
        return False
    return True


def _recipe_to_idea(recipe: "Recipe") -> RecipeIdea:
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
            fiber_g=float(recipe.macros_fiber_g)
            if recipe.macros_fiber_g is not None
            else None,
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
            Ingredient(name=ingredient.name, grams=ingredient.grams, note=ingredient.note)
            for ingredient in getattr(recipe, "ingredients", [])
        ],
        instructions=list(recipe.instructions_json or []),
        macros=macros,
        tags=tags,
        source=source,
    )


def _idea_to_suggestion(idea: RecipeIdea, source: str = "db") -> Suggestion:
    effective_source = getattr(idea, "source", None) or source
    from .schemas import SuggestionItem

    return Suggestion(
        name=idea.title,
        items=[SuggestionItem(food=ingredient.name, grams=ingredient.grams or 0.0) for ingredient in idea.ingredients],
        source=effective_source,
        est_kcal=idea.macros.kcal if idea.macros else None,
        est_protein_g=idea.macros.protein_g if idea.macros else None,
        est_carbs_g=idea.macros.carbs_g if idea.macros else None,
        est_fat_g=idea.macros.fat_g if idea.macros else None,
        est_fiber_g=idea.macros.fiber_g if idea.macros else None,
    )


def _ideas_to_suggestions(ideas: List[RecipeIdea], source: str = "db") -> List[Suggestion]:
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


def _merge_ideas(primary: List[RecipeIdea], secondary: List[RecipeIdea]) -> List[RecipeIdea]:
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
    req: ComposeRequest,
    prefs: Prefs,
    constraints: Dict[str, Any],
    ideas: List[RecipeIdea],
    source: str,
) -> None:
    if not HAS_RECIPES or not ideas:
        return

    try:
        prefs_json = (
            json.dumps(prefs.model_dump(exclude_none=True), ensure_ascii=False)
            if prefs
            else None
        )
        constraints_json = (
            json.dumps(constraints, ensure_ascii=False) if constraints else None
        )

        for idea in ideas:
            exists = session.exec(
                select(Recipe).where(
                    Recipe.title == idea.title,
                    Recipe.source == source,
                )
            ).first()
            if exists:
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
    except Exception as exc:  # pragma: no cover - defensive
        session.rollback()
        print("[WARN] Persisting recipe ideas failed:", exc)


def _build_query_text(req: ComposeRequest, prefs: Prefs, constraints: Dict[str, Any]) -> str:
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
        bits.append(
            json.dumps({k: v for k, v in constraints.items() if v is not None}, ensure_ascii=False)
        )
    return " ".join(bits)


def _recipes_matching_query(
    session: Session,
    req: ComposeRequest,
    prefs: Prefs,
    constraints: Dict[str, Any],
    limit: int,
    required_ingredients: Optional[List[str]] = None,
) -> Tuple[List[RecipeIdea], Dict[str, Any]]:
    meta = {
        "reason": None,
        "used_embeddings": False,
        "candidates_total": 0,
        "candidates_filtered": 0,
    }
    if not HAS_RECIPES:
        meta["reason"] = "recipes_table_missing"
        return [], meta

    stmt = (
        select(Recipe)
        .options(selectinload(Recipe.ingredients))
        .order_by(Recipe.created_at.desc())
    )
    if RAG_MAX_RECIPES > 0:
        stmt = stmt.limit(RAG_MAX_RECIPES)
    recipes = session.exec(stmt).all()
    meta["candidates_total"] = len(recipes)

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

    from app.rag.preprocess import QueryPreprocessor

    negative_ingredients = QueryPreprocessor.extract_negative_terms(req.message or "")
    if negative_ingredients:
        meta["negative_ingredients"] = negative_ingredients

    scored: List[Tuple[float, Recipe]] = []

    if RAG_MODULES_AVAILABLE:
        prefs_dict = prefs.model_dump(exclude_none=True) if prefs else {}
        query_text = QueryPreprocessor.build_query_text(
            message=req.message or "",
            preferences=prefs_dict,
            constraints=constraints,
            servings=req.servings,
        )

        document_texts = [QueryPreprocessor.build_document(recipe) for recipe in filtered]
        embedding_client = _embed_texts
        indexer = RecipeIndexer(session, embedding_client=embedding_client)  # type: ignore[call-arg]
        recipe_embeddings = indexer.batch_index(filtered, document_texts, force_refresh=False)
        query_vectors = embedding_client([query_text]) if embedding_client else None
        query_vec = query_vectors[0] if query_vectors and len(query_vectors) > 0 else None
        post_processor = PostProcessor(
            semantic_weight=1.0,
            nutrition_weight=0.5,
            ingredient_weight=0.3,
        )

        use_keyword_fallback = query_vec is None or not recipe_embeddings
        meta["used_embeddings"] = not use_keyword_fallback

        scored_results = post_processor.score_batch(
            recipes=filtered,
            query_vector=query_vec,
            recipe_vectors=recipe_embeddings if not use_keyword_fallback else None,
            query_text=query_text,
            constraints=constraints,
            use_keyword_fallback=use_keyword_fallback,
            negative_ingredients=negative_ingredients,
        )
        scored = post_processor.rerank(scored_results, limit=limit)
    else:
        docs = [_recipe_document(recipe) for recipe in filtered]
        query_text = _build_query_text(req, prefs, constraints)
        vectors = _embed_texts([query_text] + docs) if docs else None

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


def _retrieve_candidates(session: Session, prefs: Prefs, top_k: int = RAG_TOP_K) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    if HAS_RECIPES and Recipe is not None:
        recipes = session.exec(
            select(Recipe)
            .options(selectinload(Recipe.ingredients))
            .order_by(Recipe.created_at.desc())
            .limit(top_k)
        ).all()
        for recipe in recipes:
            title = getattr(recipe, "title", "") or ""
            text = f"{title} {getattr(recipe, 'tags', '')}"
            candidates.append(
                {
                    "type": "recipe",
                    "id": recipe.id,
                    "name": title,
                    "text": text,
                    "macros": {
                        "kcal": getattr(recipe, "macros_kcal", None),
                        "protein_g": getattr(recipe, "macros_protein_g", None),
                        "carbs_g": getattr(recipe, "macros_carbs_g", None),
                        "fat_g": getattr(recipe, "macros_fat_g", None),
                        "fiber_g": getattr(recipe, "macros_fiber_g", None),
                    },
                }
            )
    else:
        foods = session.exec(select(Food)).all()
        foods = _apply_prefs_filter_foods(foods, prefs)
        for food in foods:
            text = (
                f"{food.name} protein {getattr(food,'protein_g',0)} carbs {getattr(food,'carbs_g',0)} "
                f"fat {getattr(food,'fat_g',0)} kcal {getattr(food,'kcal',0)}"
            )
            candidates.append(
                {
                    "type": "food",
                    "id": food.id,
                    "name": food.name,
                    "text": text,
                    "kcal_100g": float(getattr(food, "kcal", 0) or 0),
                    "protein_g_100g": float(getattr(food, "protein_g", 0) or 0),
                    "carbs_g_100g": float(getattr(food, "carbs_g", 0) or 0),
                    "fat_g_100g": float(getattr(food, "fat_g", 0) or 0),
                }
            )

    vecs = _embed_texts([candidate["text"] for candidate in candidates]) if candidates else None
    if vecs:
        q_vecs = _embed_texts(["high protein simple snack balanced macros"])
        if q_vecs:
            qv = q_vecs[0]
            scored = [(candidate, _cosine(qv, vector)) for candidate, vector in zip(candidates, vecs)]
            scored.sort(key=lambda x: x[1], reverse=True)
            candidates = [candidate for candidate, _ in scored[:top_k]]
        else:
            candidates = candidates[:top_k]
    else:
        if candidates and candidates[0]["type"] == "food":
            candidates.sort(
                key=lambda candidate: (
                    candidate["protein_g_100g"] / (candidate["kcal_100g"] + 1e-6)
                    if candidate["kcal_100g"] > 0
                    else 0
                ),
                reverse=True,
            )
        candidates = candidates[:top_k]

    return candidates

