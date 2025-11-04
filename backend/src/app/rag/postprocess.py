"""Post-processing for RAG retrieval results.

This module handles scoring, filtering, and re-ranking of retrieved recipes.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app.models.recipes import Recipe
from app.rag.preprocess import QueryPreprocessor


class PostProcessor:
    """Post-processes retrieved recipes with scoring and filtering."""

    def __init__(
        self,
        semantic_weight: float = 1.0,
        nutrition_weight: float = 0.5,
        ingredient_weight: float = 0.3,
    ):
        """Initialize post-processor with scoring weights.

        Args:
            semantic_weight: Weight for cosine similarity (embedding) score
            nutrition_weight: Weight for nutrition fit score
            ingredient_weight: Weight for ingredient overlap score
        """
        self.semantic_weight = semantic_weight
        self.nutrition_weight = nutrition_weight
        self.ingredient_weight = ingredient_weight

    @staticmethod
    def cosine_similarity(a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            a: First vector
            b: Second vector

        Returns:
            Cosine similarity score (0-1)
        """
        if not a or not b or len(a) != len(b):
            return 0.0

        num = sum(x * y for x, y in zip(a, b))
        da = math.sqrt(sum(x * x for x in a))
        db = math.sqrt(sum(y * y for y in b))
        denom = da * db + 1e-9  # Small epsilon to avoid division by zero
        return num / denom

    @staticmethod
    def nutrition_fit_score(recipe: Recipe, constraints: Dict[str, Any]) -> float:
        """Calculate how well recipe fits nutritional constraints.

        Args:
            recipe: Recipe to score
            constraints: Constraints dict with keys like 'max_kcal', 'remaining_kcal', etc.

        Returns:
            Score between 0 and 1 (higher = better fit)
        """
        if not constraints or getattr(recipe, "macros_kcal", None) is None:
            return 0.0

        kcal = float(recipe.macros_kcal or 0.0)
        remaining = constraints.get("remaining_kcal")
        max_kcal = constraints.get("max_kcal")
        score = 0.0

        # Score based on how close we are to remaining kcal target
        if remaining is not None:
            target = max(remaining, 0.0)
            if target > 0:
                diff = abs(kcal - target)
                denom = max(target, 1.0)
                score += max(0.0, 1.0 - diff / denom)

        # Score based on max_kcal constraint
        if max_kcal is not None:
            if kcal <= max_kcal:
                score += 0.3
            else:
                # Penalize if over max_kcal
                overage = kcal - max_kcal
                penalty = min(1.0, overage / max(max_kcal, 1.0))
                score -= penalty

        return max(0.0, min(1.0, score))  # Clamp to [0, 1]

    @staticmethod
    def ingredient_overlap_score(recipe: Recipe, query_text: str) -> float:
        """Calculate overlap between query and recipe ingredients.

        Args:
            recipe: Recipe to score
            query_text: User query text

        Returns:
            Overlap score between 0 and 1
        """
        if not query_text:
            return 0.0

        query_tokens = set(QueryPreprocessor.tokenize(query_text))
        if not query_tokens:
            return 0.0

        # Collect ingredient tokens
        ingredient_tokens: set[str] = set()
        ingredients = getattr(recipe, "ingredients", []) or []
        for ingredient in ingredients:
            name = getattr(ingredient, "name", "") or ""
            ingredient_tokens.update(QueryPreprocessor.tokenize(name))

        if not ingredient_tokens:
            return 0.0

        # Calculate overlap ratio
        overlap = len(query_tokens & ingredient_tokens)
        return overlap / max(len(query_tokens), 1)

    @staticmethod
    def keyword_overlap_score(query_tokens: List[str], doc_tokens: List[str]) -> float:
        """Calculate keyword overlap between query and document.

        Args:
            query_tokens: Tokenized query
            doc_tokens: Tokenized document

        Returns:
            Overlap score between 0 and 1
        """
        if not query_tokens or not doc_tokens:
            return 0.0

        qs, ds = set(query_tokens), set(doc_tokens)
        overlap = len(qs & ds)
        return overlap / max(len(qs), 1)

    def score_recipe(
        self,
        recipe: Recipe,
        query_vector: Optional[List[float]] = None,
        recipe_vector: Optional[List[float]] = None,
        query_text: str = "",
        constraints: Optional[Dict[str, Any]] = None,
        use_keyword_fallback: bool = False,
    ) -> float:
        """Calculate combined score for a recipe.

        Args:
            recipe: Recipe to score
            query_vector: Query embedding vector (if available)
            recipe_vector: Recipe embedding vector (if available)
            query_text: Original query text
            constraints: Nutritional constraints
            use_keyword_fallback: If True, use keyword matching instead of embeddings

        Returns:
            Combined score (higher = better match)
        """
        score = 0.0

        # Semantic similarity (embedding-based)
        if not use_keyword_fallback and query_vector and recipe_vector:
            semantic_score = self.cosine_similarity(query_vector, recipe_vector)
            score += self.semantic_weight * semantic_score

        # Keyword overlap (fallback when embeddings unavailable)
        if use_keyword_fallback or not (query_vector and recipe_vector):
            query_tokens = QueryPreprocessor.tokenize(query_text)
            doc_text = QueryPreprocessor.build_document(recipe)
            doc_tokens = QueryPreprocessor.tokenize(doc_text)
            keyword_score = self.keyword_overlap_score(query_tokens, doc_tokens)
            score += self.semantic_weight * keyword_score

        # Nutrition fit
        if constraints:
            nutrition_score = self.nutrition_fit_score(recipe, constraints)
            score += self.nutrition_weight * nutrition_score

        # Ingredient overlap
        if query_text:
            ingredient_score = self.ingredient_overlap_score(recipe, query_text)
            score += self.ingredient_weight * ingredient_score

        return score

    def score_batch(
        self,
        recipes: List[Recipe],
        query_vector: Optional[List[float]],
        recipe_vectors: Optional[Dict[int, List[float]]],
        query_text: str,
        constraints: Optional[Dict[str, Any]] = None,
        use_keyword_fallback: bool = False,
    ) -> List[Tuple[float, Recipe]]:
        """Score a batch of recipes.

        Args:
            recipes: List of recipes to score
            query_vector: Query embedding vector
            recipe_vectors: Dictionary mapping recipe_id -> embedding vector
            query_text: Original query text
            constraints: Nutritional constraints
            use_keyword_fallback: If True, use keyword matching

        Returns:
            List of (score, recipe) tuples, sorted by score (descending)
        """
        scored: List[Tuple[float, Recipe]] = []

        for recipe in recipes:
            recipe_vec = recipe_vectors.get(recipe.id) if recipe_vectors else None
            score = self.score_recipe(
                recipe=recipe,
                query_vector=query_vector,
                recipe_vector=recipe_vec,
                query_text=query_text,
                constraints=constraints or {},
                use_keyword_fallback=use_keyword_fallback,
            )
            scored.append((score, recipe))

        # Sort by score (descending)
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def filter_by_constraints(
        self,
        recipes: List[Recipe],
        constraints: Dict[str, Any],
    ) -> List[Recipe]:
        """Filter recipes based on constraints.

        Args:
            recipes: List of recipes to filter
            constraints: Constraints dict (e.g., {'max_kcal': 800})

        Returns:
            Filtered list of recipes
        """
        filtered = []
        max_kcal = constraints.get("max_kcal")

        for recipe in recipes:
            # Check max_kcal constraint
            if max_kcal is not None and recipe.macros_kcal is not None:
                if recipe.macros_kcal > max_kcal:
                    continue

            filtered.append(recipe)

        return filtered

    def rerank(
        self,
        scored_recipes: List[Tuple[float, Recipe]],
        limit: Optional[int] = None,
    ) -> List[Tuple[float, Recipe]]:
        """Re-rank and optionally limit results.

        Args:
            scored_recipes: List of (score, recipe) tuples (should already be sorted)
            limit: Optional limit on number of results

        Returns:
            Re-ranked (and possibly limited) results
        """
        if limit is not None:
            return scored_recipes[:limit]
        return scored_recipes
