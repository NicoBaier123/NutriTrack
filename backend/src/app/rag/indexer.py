"""Recipe embedding indexer with caching support.

This module provides a caching layer for recipe embeddings to avoid recomputing
vectors on every request. Embeddings are stored in a SQLite table for persistence.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from sqlalchemy import Column, JSON, Text
from sqlmodel import Field, Session, SQLModel, create_engine, select

from app.models.recipes import Recipe


class RecipeEmbedding(SQLModel, table=True):
    """SQLite table for storing recipe embeddings."""

    __tablename__ = "recipe_embeddings"

    recipe_id: int = Field(primary_key=True, foreign_key="recipe.id")
    embedding: List[float] = Field(
        sa_column=Column(JSON, nullable=False), description="Vector embedding (384-dim for all-MiniLM-L6-v2)"
    )
    document_text: str = Field(sa_column=Column(Text, nullable=False), description="Original document text used for embedding")
    model_name: str = Field(default="all-MiniLM-L6-v2", description="Embedding model used")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")


class RecipeIndexer:
    """Manages recipe embeddings with caching in SQLite."""

    def __init__(
        self,
        session: Session,
        embedding_client: Optional[Callable[[List[str]], Optional[List[List[float]]]]] = None,
        index_table_name: str = "recipe_embeddings",
    ):
        """Initialize the indexer.

        Args:
            session: SQLModel database session
            embedding_client: Function that takes List[str] and returns List[List[float]]
            index_table_name: Name of the embedding storage table
        """
        self.session = session
        self.embedding_client = embedding_client
        self.index_table_name = index_table_name

    def _embed_texts(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Call embedding service. Falls back to None if unavailable."""
        if not self.embedding_client:
            return None
        try:
            return self.embedding_client(texts)
        except Exception:
            return None

    def _ensure_table_exists(self) -> None:
        """Ensure the embedding table exists in the database."""
        SQLModel.metadata.create_all(self.session.bind)

    def get_embedding(self, recipe_id: int) -> Optional[List[float]]:
        """Get cached embedding for a recipe.

        Args:
            recipe_id: Recipe ID to look up

        Returns:
            Embedding vector or None if not found
        """
        self._ensure_table_exists()
        record = self.session.exec(select(RecipeEmbedding).where(RecipeEmbedding.recipe_id == recipe_id)).first()
        return record.embedding if record else None

    def get_embeddings_batch(self, recipe_ids: List[int]) -> Dict[int, List[float]]:
        """Get cached embeddings for multiple recipes.

        Args:
            recipe_ids: List of recipe IDs

        Returns:
            Dictionary mapping recipe_id -> embedding
        """
        self._ensure_table_exists()
        records = self.session.exec(
            select(RecipeEmbedding).where(RecipeEmbedding.recipe_id.in_(recipe_ids))
        ).all()
        return {r.recipe_id: r.embedding for r in records}

    def index_recipe(self, recipe: Recipe, document_text: str, force_refresh: bool = False) -> Optional[List[float]]:
        """Index a single recipe, using cache if available.

        Args:
            recipe: Recipe to index
            document_text: Preprocessed document text for this recipe
            force_refresh: If True, recompute embedding even if cached

        Returns:
            Embedding vector or None if embedding service unavailable
        """
        self._ensure_table_exists()

        # Check cache first
        if not force_refresh:
            cached = self.get_embedding(recipe.id)
            if cached:
                return cached

        # Compute embedding
        embeddings = self._embed_texts([document_text])
        if not embeddings or not embeddings[0]:
            return None

        embedding = embeddings[0]

        # Store in cache
        existing = self.session.exec(
            select(RecipeEmbedding).where(RecipeEmbedding.recipe_id == recipe.id)
        ).first()

        if existing:
            existing.embedding = embedding
            existing.document_text = document_text
            existing.updated_at = datetime.utcnow()
        else:
            self.session.add(
                RecipeEmbedding(
                    recipe_id=recipe.id,
                    embedding=embedding,
                    document_text=document_text,
                    model_name="all-MiniLM-L6-v2",
                    updated_at=datetime.utcnow(),
                )
            )

        self.session.commit()
        return embedding

    def batch_index(self, recipes: List[Recipe], document_texts: List[str], force_refresh: bool = False) -> Dict[int, List[float]]:
        """Index multiple recipes, using cache where possible.

        Args:
            recipes: List of recipes to index
            document_texts: Preprocessed document texts (one per recipe)
            force_refresh: If True, recompute all embeddings

        Returns:
            Dictionary mapping recipe_id -> embedding
        """
        if len(recipes) != len(document_texts):
            raise ValueError("recipes and document_texts must have same length")

        self._ensure_table_exists()

        recipe_ids = [r.id for r in recipes]
        cached_embeddings = {} if force_refresh else self.get_embeddings_batch(recipe_ids)

        # Find recipes that need embedding
        to_embed: List[tuple[int, str, Recipe]] = []
        for recipe, doc_text in zip(recipes, document_texts):
            if recipe.id not in cached_embeddings:
                to_embed.append((recipe.id, doc_text, recipe))

        # Batch embed missing recipes
        if to_embed:
            texts_to_embed = [doc_text for _, doc_text, _ in to_embed]
            embeddings = self._embed_texts(texts_to_embed)

            if embeddings and len(embeddings) == len(to_embed):
                for (recipe_id, doc_text, recipe), embedding in zip(to_embed, embeddings):
                    cached_embeddings[recipe_id] = embedding

                    # Store in cache
                    existing = self.session.exec(
                        select(RecipeEmbedding).where(RecipeEmbedding.recipe_id == recipe_id)
                    ).first()

                    if existing:
                        existing.embedding = embedding
                        existing.document_text = doc_text
                        existing.updated_at = datetime.utcnow()
                    else:
                        self.session.add(
                            RecipeEmbedding(
                                recipe_id=recipe_id,
                                embedding=embedding,
                                document_text=doc_text,
                                model_name="all-MiniLM-L6-v2",
                                updated_at=datetime.utcnow(),
                            )
                        )

                self.session.commit()

        return cached_embeddings

    def refresh_recipe(self, recipe: Recipe, document_text: str) -> Optional[List[float]]:
        """Force refresh of a recipe's embedding.

        Args:
            recipe: Recipe to refresh
            document_text: Preprocessed document text

        Returns:
            New embedding vector or None if unavailable
        """
        return self.index_recipe(recipe, document_text, force_refresh=True)

    def build_index(self, recipes: List[Recipe], document_texts: List[str]) -> Dict[int, List[float]]:
        """Build index for all recipes (alias for batch_index with force_refresh=False).

        Args:
            recipes: List of recipes to index
            document_texts: Preprocessed document texts

        Returns:
            Dictionary mapping recipe_id -> embedding
        """
        return self.batch_index(recipes, document_texts, force_refresh=False)

    def get_cached_count(self) -> int:
        """Get number of cached embeddings.

        Returns:
            Count of cached embeddings
        """
        self._ensure_table_exists()
        return len(self.session.exec(select(RecipeEmbedding)).all())

    def clear_index(self) -> None:
        """Clear all cached embeddings."""
        self._ensure_table_exists()
        records = self.session.exec(select(RecipeEmbedding)).all()
        for record in records:
            self.session.delete(record)
        self.session.commit()
