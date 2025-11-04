"""Query and document preprocessing for RAG.

This module handles normalization of user queries and recipe documents
before embedding and retrieval.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.models.recipes import Recipe


class QueryPreprocessor:
    """Preprocesses queries and recipe documents for embedding."""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text by cleaning whitespace and special characters.

        Args:
            text: Raw text input

        Returns:
            Normalized text
        """
        if not text:
            return ""
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text.strip())
        # Remove excessive punctuation (keep basic sentence structure)
        text = re.sub(r"[^\w\s.,!?äöüß-]", " ", text)
        return text.strip()

    @staticmethod
    def tokenize(text: str) -> List[str]:
        """Tokenize text into words (lowercase, alphanumeric + German umlauts).

        Args:
            text: Text to tokenize

        Returns:
            List of tokens
        """
        if not text:
            return []
        return re.findall(r"[a-z0-9äöüß]+", text.lower())

    @staticmethod
    def build_document(recipe: Recipe) -> str:
        """Build document text from recipe metadata for embedding.

        This is the text representation that gets embedded. It includes:
        - Title
        - Tags
        - Instructions
        - Ingredients with amounts
        - Macro information

        Args:
            recipe: Recipe to convert to document text

        Returns:
            Normalized document text
        """
        parts: List[str] = []

        # Title
        if recipe.title:
            parts.append(recipe.title)

        # Tags
        if recipe.tags:
            parts.append(recipe.tags)

        # Instructions
        if recipe.instructions_json:
            parts.extend(recipe.instructions_json)

        # Ingredients with grams
        ingredients = getattr(recipe, "ingredients", []) or []
        for ing in ingredients:
            name = getattr(ing, "name", "") or ""
            grams = getattr(ing, "grams", None)
            if name:
                if grams:
                    parts.append(f"{name} {grams}g")
                else:
                    parts.append(name)

        # Macro information
        if recipe.macros_kcal:
            parts.append(f"{recipe.macros_kcal} kcal")
        if recipe.macros_protein_g:
            parts.append(f"{recipe.macros_protein_g} g protein")
        if recipe.macros_carbs_g:
            parts.append(f"{recipe.macros_carbs_g} g carbs")
        if recipe.macros_fat_g:
            parts.append(f"{recipe.macros_fat_g} g fat")

        # Join and normalize
        doc_text = " ".join(part for part in parts if part)
        return QueryPreprocessor.normalize_text(doc_text)

    @staticmethod
    def build_query_text(
        message: str,
        preferences: Optional[Dict[str, Any]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        servings: Optional[int] = None,
    ) -> str:
        """Build normalized query text from user request components.

        Args:
            message: User's query message
            preferences: User preferences (veggie, vegan, etc.)
            constraints: Nutritional constraints (max_kcal, etc.)
            servings: Number of servings

        Returns:
            Normalized query text ready for embedding
        """
        bits: List[str] = []

        # Main message
        if message:
            bits.append(QueryPreprocessor.normalize_text(message))

        # Servings
        if servings:
            bits.append(f"servings {servings}")

        # Preferences
        if preferences:
            pref_str = json.dumps(preferences, ensure_ascii=False)
            bits.append(QueryPreprocessor.normalize_text(pref_str))

        # Constraints
        if constraints:
            # Filter None values for cleaner text
            filtered_constraints = {k: v for k, v in constraints.items() if v is not None}
            if filtered_constraints:
                constraint_str = json.dumps(filtered_constraints, ensure_ascii=False)
                bits.append(QueryPreprocessor.normalize_text(constraint_str))

        query_text = " ".join(bits)
        return QueryPreprocessor.normalize_text(query_text)

    @staticmethod
    def clean_query(query: str) -> str:
        """Clean and normalize a query string.

        Args:
            query: Raw query string

        Returns:
            Cleaned query string
        """
        return QueryPreprocessor.normalize_text(query)
