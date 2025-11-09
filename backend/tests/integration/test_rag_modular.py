"""Integration tests for modular RAG system.

Tests cover:
- Indexer: build/load, caching
- Preprocessor: text normalization, document building, query building
- Postprocessor: scoring, filtering
- End-to-end RAG pipeline
"""

import pytest
from datetime import date
from typing import List
from sqlmodel import Session, select

from app.models.recipes import Recipe, RecipeItem
from app.models.foods import Food
from app.rag.indexer import RecipeIndexer, RecipeEmbedding
from app.rag.preprocess import QueryPreprocessor
from app.rag.postprocess import PostProcessor
from app.routers.advisor.helpers import _infer_required_ingredients


# Mock embedding client that returns dummy vectors
def _mock_embedding_client(texts: List[str]) -> List[List[float]]:
    """Mock embedding client that returns 384-dim vectors (all-MiniLM-L6-v2 size)."""
    return [[0.1] * 384 for _ in texts]


@pytest.fixture
def sample_recipes(db_session: Session) -> List[Recipe]:
    """Create sample recipes for testing."""
    recipes = [
        Recipe(
            title="High Protein Oatmeal",
            tags="breakfast,protein,healthy",
            instructions_json=["Mix oats with protein powder", "Add milk", "Cook for 5 minutes"],
            macros_kcal=450.0,
            macros_protein_g=30.0,
            macros_carbs_g=50.0,
            macros_fat_g=10.0,
        ),
        Recipe(
            title="Chicken Rice Bowl",
            tags="lunch,dinner,protein,balanced",
            instructions_json=["Cook chicken", "Prepare rice", "Combine in bowl"],
            macros_kcal=600.0,
            macros_protein_g=45.0,
            macros_carbs_g=65.0,
            macros_fat_g=15.0,
        ),
        Recipe(
            title="Vegetarian Pasta",
            tags="vegetarian,dinner,carbs",
            instructions_json=["Boil pasta", "Add vegetables", "Serve hot"],
            macros_kcal=550.0,
            macros_protein_g=20.0,
            macros_carbs_g=80.0,
            macros_fat_g=12.0,
        ),
    ]

    for recipe in recipes:
        db_session.add(recipe)
    db_session.commit()

    for recipe in recipes:
        db_session.refresh(recipe)
        # Add ingredients
        ingredients = [
            RecipeItem(recipe_id=recipe.id, name="Ingredient 1", grams=100.0),
            RecipeItem(recipe_id=recipe.id, name="Ingredient 2", grams=50.0),
        ]
        for ing in ingredients:
            db_session.add(ing)
    db_session.commit()

    for recipe in recipes:
        db_session.refresh(recipe)

    return recipes


# ==================== Indexer Tests ====================


def test_indexer_get_embedding_cached(db_session: Session, sample_recipes: List[Recipe]):
    """Test that indexer retrieves cached embeddings."""
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)

    recipe = sample_recipes[0]
    doc_text = QueryPreprocessor.build_document(recipe)

    # Index recipe
    embedding = indexer.index_recipe(recipe, doc_text)
    assert embedding is not None
    assert len(embedding) == 384

    # Retrieve from cache
    cached = indexer.get_embedding(recipe.id)
    assert cached == embedding


def test_indexer_batch_index(db_session: Session, sample_recipes: List[Recipe]):
    """Test batch indexing of multiple recipes."""
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)

    recipes = sample_recipes
    doc_texts = [QueryPreprocessor.build_document(r) for r in recipes]

    # Batch index
    embeddings = indexer.batch_index(recipes, doc_texts)
    assert len(embeddings) == len(recipes)

    # Verify all are cached
    for recipe in recipes:
        assert recipe.id in embeddings
        cached = indexer.get_embedding(recipe.id)
        assert cached is not None


def test_indexer_refresh_recipe(db_session: Session, sample_recipes: List[Recipe]):
    """Test that refresh_recipe recomputes embeddings."""
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)

    recipe = sample_recipes[0]
    doc_text = QueryPreprocessor.build_document(recipe)

    # Index recipe
    embedding1 = indexer.index_recipe(recipe, doc_text)
    assert embedding1 is not None

    # Refresh (should recompute)
    embedding2 = indexer.refresh_recipe(recipe, doc_text)
    assert embedding2 is not None
    # Note: With mock client, embeddings will be identical, but in real scenario they could differ


def test_indexer_get_cached_count(db_session: Session, sample_recipes: List[Recipe]):
    """Test counting cached embeddings."""
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)

    assert indexer.get_cached_count() == 0

    recipes = sample_recipes[:2]
    doc_texts = [QueryPreprocessor.build_document(r) for r in recipes]
    indexer.batch_index(recipes, doc_texts)

    assert indexer.get_cached_count() == 2


def test_indexer_clear_index(db_session: Session, sample_recipes: List[Recipe]):
    """Test clearing the index."""
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)

    recipes = sample_recipes
    doc_texts = [QueryPreprocessor.build_document(r) for r in recipes]
    indexer.batch_index(recipes, doc_texts)

    assert indexer.get_cached_count() == len(recipes)

    indexer.clear_index()
    assert indexer.get_cached_count() == 0


# ==================== Preprocessor Tests ====================


def test_preprocessor_normalize_text():
    """Test text normalization."""
    # Test whitespace normalization
    assert QueryPreprocessor.normalize_text("  hello   world  ") == "hello world"

    # Test special character removal
    text = "Hello! This is a test@#$"
    normalized = QueryPreprocessor.normalize_text(text)
    assert "@" not in normalized
    assert "#" not in normalized


def test_preprocessor_tokenize():
    """Test text tokenization."""
    tokens = QueryPreprocessor.tokenize("Hello World! Test 123")
    assert "hello" in tokens
    assert "world" in tokens
    assert "test" in tokens
    assert "123" in tokens


def test_preprocessor_build_document(sample_recipes: List[Recipe]):
    """Test building document text from recipe."""
    recipe = sample_recipes[0]
    doc_text = QueryPreprocessor.build_document(recipe)

    assert recipe.title in doc_text
    assert recipe.tags in doc_text
    assert "450" in doc_text  # macros_kcal
    assert "30" in doc_text  # macros_protein_g


def test_preprocessor_build_query_text():
    """Test building query text from components."""
    query = QueryPreprocessor.build_query_text(
        message="high protein breakfast",
        preferences={"vegan": True},
        constraints={"max_kcal": 500},
        servings=2,
    )

    assert "high protein breakfast" in query
    assert "servings 2" in query
    # Preferences and constraints should be in JSON format
    assert "vegan" in query.lower() or "true" in query


def test_preprocessor_extract_negative_terms():
    terms = QueryPreprocessor.extract_negative_terms("No mango smoothie bowl without nuts")
    assert "mango" in terms
    assert "nuts" in terms
    # Duplicates should be suppressed
    duplicate_terms = QueryPreprocessor.extract_negative_terms("no mango, no mango please")
    assert duplicate_terms.count("mango") == 1


def test_infer_required_ingredients_skips_negations(db_session: Session):
    banana = Food(name="Banana", kcal=89.0, protein_g=1.1, carbs_g=23.0, fat_g=0.3, fiber_g=2.6)
    db_session.add(banana)
    db_session.commit()

    matches = _infer_required_ingredients(db_session, "no banana smoothie bowl")
    assert matches == []


# ==================== Postprocessor Tests ====================


def test_postprocessor_cosine_similarity():
    """Test cosine similarity calculation."""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [1.0, 0.0, 0.0]
    assert abs(PostProcessor.cosine_similarity(vec1, vec2) - 1.0) < 0.001

    vec1 = [1.0, 0.0]
    vec2 = [0.0, 1.0]
    assert abs(PostProcessor.cosine_similarity(vec1, vec2) - 0.0) < 0.001


def test_postprocessor_nutrition_fit_score(sample_recipes: List[Recipe]):
    """Test nutrition fit scoring."""
    recipe = sample_recipes[0]  # 450 kcal
    constraints = {"remaining_kcal": 500, "max_kcal": 600}

    score = PostProcessor.nutrition_fit_score(recipe, constraints)
    assert 0.0 <= score <= 1.0
    assert score > 0  # Should have some score


def test_postprocessor_ingredient_overlap_score(sample_recipes: List[Recipe]):
    """Test ingredient overlap scoring."""
    recipe = sample_recipes[0]
    query = "Ingredient 1 protein"

    score = PostProcessor.ingredient_overlap_score(recipe, query)
    assert 0.0 <= score <= 1.0
    assert score > 0  # Should have overlap


def test_postprocessor_keyword_overlap_score():
    """Test keyword overlap scoring."""
    query_tokens = ["protein", "breakfast", "healthy"]
    doc_tokens = ["protein", "breakfast", "oats"]

    score = PostProcessor.keyword_overlap_score(query_tokens, doc_tokens)
    assert 0.0 <= score <= 1.0
    assert score > 0


def test_postprocessor_score_recipe_with_embeddings(sample_recipes: List[Recipe]):
    """Test scoring a recipe with embeddings."""
    processor = PostProcessor()
    recipe = sample_recipes[0]
    query_vec = [0.1] * 384
    recipe_vec = [0.1] * 384

    score = processor.score_recipe(
        recipe=recipe,
        query_vector=query_vec,
        recipe_vector=recipe_vec,
        query_text="high protein",
        constraints={"max_kcal": 500},
        use_keyword_fallback=False,
    )

    assert score is not None
    assert score > 0


def test_postprocessor_score_recipe_keyword_fallback(sample_recipes: List[Recipe]):
    """Test scoring a recipe with keyword fallback."""
    processor = PostProcessor()
    recipe = sample_recipes[0]

    score = processor.score_recipe(
        recipe=recipe,
        query_text="protein breakfast",
        constraints={"max_kcal": 500},
        use_keyword_fallback=True,
    )

    assert score is not None
    assert score > 0


def test_postprocessor_filters_negative_ingredients(sample_recipes: List[Recipe]):
    processor = PostProcessor()
    recipe = sample_recipes[0]

    score = processor.score_recipe(
        recipe=recipe,
        query_text="no mango smoothie bowl",
        use_keyword_fallback=True,
        negative_ingredients=["ingredient"],
    )

    assert score is None


def test_postprocessor_score_batch(sample_recipes: List[Recipe]):
    """Test batch scoring of recipes."""
    processor = PostProcessor()
    recipes = sample_recipes
    query_vec = [0.1] * 384
    recipe_vectors = {r.id: [0.1] * 384 for r in recipes}

    scored = processor.score_batch(
        recipes=recipes,
        query_vector=query_vec,
        recipe_vectors=recipe_vectors,
        query_text="protein meal",
        constraints={"max_kcal": 700},
        use_keyword_fallback=False,
    )

    assert len(scored) == len(recipes)
    # Should be sorted by score (descending)
    scores = [s[0] for s in scored]
    assert scores == sorted(scores, reverse=True)


def test_postprocessor_filter_by_constraints(sample_recipes: List[Recipe]):
    """Test filtering recipes by constraints."""
    processor = PostProcessor()
    recipes = sample_recipes
    constraints = {"max_kcal": 500}

    filtered = processor.filter_by_constraints(recipes, constraints)
    # Only recipes with kcal <= 500 should pass
    assert all(r.macros_kcal <= 500 for r in filtered)


# ==================== End-to-End Tests ====================


def test_end_to_end_rag_pipeline(db_session: Session, sample_recipes: List[Recipe]):
    """Test complete RAG pipeline from indexing to retrieval."""
    # Initialize components
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)
    preprocessor = QueryPreprocessor()
    postprocessor = PostProcessor()

    # Step 1: Build and index documents
    recipes = sample_recipes
    doc_texts = [preprocessor.build_document(r) for r in recipes]
    recipe_embeddings = indexer.batch_index(recipes, doc_texts)
    assert len(recipe_embeddings) == len(recipes)

    # Step 2: Build query
    query_text = preprocessor.build_query_text(
        message="high protein breakfast",
        constraints={"max_kcal": 500},
    )

    # Step 3: Embed query
    query_vectors = _mock_embedding_client([query_text])
    query_vec = query_vectors[0]

    # Step 4: Score and rank
    scored = postprocessor.score_batch(
        recipes=recipes,
        query_vector=query_vec,
        recipe_vectors=recipe_embeddings,
        query_text=query_text,
        constraints={"max_kcal": 500},
        use_keyword_fallback=False,
    )

    # Step 5: Filter and limit
    filtered = postprocessor.filter_by_constraints([r for _, r in scored], {"max_kcal": 500})
    final = postprocessor.rerank([(s, r) for s, r in scored if r in filtered], limit=2)

    # Verify results
    assert len(final) <= 2
    assert all(r in recipes for _, r in final)


def test_indexer_uses_cache_on_second_call(db_session: Session, sample_recipes: List[Recipe]):
    """Test that indexer uses cache on subsequent calls."""
    indexer = RecipeIndexer(db_session, embedding_client=_mock_embedding_client)

    recipe = sample_recipes[0]
    doc_text = QueryPreprocessor.build_document(recipe)

    # First call - should compute
    embedding1 = indexer.index_recipe(recipe, doc_text)
    assert embedding1 is not None

    # Second call - should use cache
    embedding2 = indexer.index_recipe(recipe, doc_text)
    assert embedding2 == embedding1
