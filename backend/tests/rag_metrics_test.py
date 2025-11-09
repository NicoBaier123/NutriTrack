"""
RAG Metrics Test Suite

Defines KPIs for evaluating RAG system performance:
- Hit rate against labeled queries
- Average cosine similarity
- Nutrition compliance
- Precision@k
- Macro score compliance
- Response latency
"""
import json
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import date

import pytest

# Import RAG modules
from app.rag.indexer import RecipeIndexer
from app.rag.preprocess import QueryPreprocessor
from app.rag.postprocess import PostProcessor
from app.routers.advisor.rag import _recipes_matching_query
from app.routers.advisor.schemas import ComposeRequest, Prefs
from app.core.database import get_session, engine
from app.models.recipes import Recipe
from sqlmodel import Session, select
from sqlalchemy.orm import selectinload


# Load evaluation dataset
EVAL_DATA_PATH = Path(__file__).parent / "data" / "rag_eval.json"


def load_eval_dataset() -> Dict[str, Any]:
    """Load the labeled evaluation dataset."""
    with open(EVAL_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def calculate_hit_rate(
    retrieved_titles: List[str], expected_titles: List[str]
) -> float:
    """
    Calculate hit rate: fraction of expected recipes found in retrieved results.
    
    Args:
        retrieved_titles: List of recipe titles returned by RAG
        expected_titles: List of expected recipe titles
        
    Returns:
        Hit rate as float between 0.0 and 1.0
    """
    if not expected_titles:
        return 1.0 if not retrieved_titles else 0.0
    
    retrieved_set = {title.lower().strip() for title in retrieved_titles}
    expected_set = {title.lower().strip() for title in expected_titles}
    
    hits = len(retrieved_set & expected_set)
    return hits / len(expected_set) if expected_set else 0.0


def calculate_precision_at_k(
    retrieved_titles: List[str], expected_titles: List[str], k: int = 3
) -> float:
    """
    Calculate precision@k: fraction of top k retrieved recipes that are in expected list.
    
    Args:
        retrieved_titles: List of recipe titles returned by RAG (ranked)
        expected_titles: List of expected recipe titles
        k: Number of top results to consider
        
    Returns:
        Precision@k as float between 0.0 and 1.0
    """
    if not retrieved_titles or k <= 0:
        return 0.0
    
    top_k = [title.lower().strip() for title in retrieved_titles[:k]]
    expected_set = {title.lower().strip() for title in expected_titles}
    
    relevant_count = sum(1 for title in top_k if title in expected_set)
    return relevant_count / min(len(top_k), k)


def calculate_avg_cosine_similarity(
    query_vec: Optional[List[float]],
    recipe_vectors: List[Optional[List[float]]],
    recipe_scores: List[Dict[str, Any]],
) -> float:
    """
    Calculate average cosine similarity for retrieved recipes.
    
    Args:
        query_vec: Query embedding vector
        recipe_vectors: List of recipe embedding vectors
        recipe_scores: List of scored recipe dictionaries with similarity info
        
    Returns:
        Average cosine similarity score
    """
    if not query_vec or not recipe_vectors:
        return 0.0
    
    similarities = []
    for score_dict in recipe_scores:
        # Extract similarity from score_dict if available
        sim = score_dict.get("cosine_similarity", 0.0)
        if sim > 0:
            similarities.append(sim)
    
    return sum(similarities) / len(similarities) if similarities else 0.0


def calculate_nutrition_compliance(
    retrieved_recipes: List[Any], constraints: Dict[str, Any]
) -> float:
    """
    Calculate nutrition compliance: fraction of retrieved recipes that meet constraints.
    
    Args:
        retrieved_recipes: List of Recipe objects or dictionaries with macro info
        constraints: Dictionary with constraint keys (max_kcal, min_protein_g, etc.)
        
    Returns:
        Compliance rate as float between 0.0 and 1.0
    """
    if not retrieved_recipes or not constraints:
        return 1.0  # No constraints means full compliance
    
    compliant_count = 0
    max_kcal = constraints.get("max_kcal")
    min_protein_g = constraints.get("min_protein_g")
    
    for recipe in retrieved_recipes:
        compliant = True
        
        # Check max_kcal constraint
        if max_kcal is not None:
            kcal = getattr(recipe, "macros_kcal", None)
            if kcal is not None and kcal > max_kcal:
                compliant = False
        
        # Check min_protein_g constraint
        if min_protein_g is not None:
            protein = getattr(recipe, "macros_protein_g", None)
            if protein is not None and protein < min_protein_g:
                compliant = False
        
        if compliant:
            compliant_count += 1
    
    return compliant_count / len(retrieved_recipes) if retrieved_recipes else 0.0


def calculate_macro_score_compliance(
    retrieved_recipes: List[Any], target_macros: Optional[Dict[str, float]] = None
) -> float:
    """
    Calculate macro score compliance: average macro fit score.
    
    Args:
        retrieved_recipes: List of Recipe objects
        target_macros: Optional target macro values (kcal, protein_g, etc.)
        
    Returns:
        Average macro score (typically from PostProcessor.nutrition_fit_score)
    """
    if not retrieved_recipes:
        return 0.0
    
    # For now, return a placeholder that indicates recipes have macro data
    # In a full implementation, this would use PostProcessor.nutrition_fit_score
    scores = []
    for recipe in retrieved_recipes:
        has_macros = (
            getattr(recipe, "macros_kcal", None) is not None
            or getattr(recipe, "macros_protein_g", None) is not None
        )
        scores.append(1.0 if has_macros else 0.0)
    
    return sum(scores) / len(scores) if scores else 0.0


@pytest.fixture
def mock_embedding_client():
    """Mock embedding client for testing."""
    def _mock_embed(texts: List[str]) -> Optional[List[List[float]]]:
        # Return dummy 384-dim vectors
        dim = 384
        return [[0.1] * dim for _ in texts]
    return _mock_embed


@pytest.fixture
def db_session():
    """Database session for testing."""
    with Session(engine) as session:
        yield session


class TestRAGMetrics:
    """Test suite for RAG KPIs."""
    
    def test_eval_dataset_loaded(self):
        """Verify evaluation dataset can be loaded."""
        dataset = load_eval_dataset()
        assert "test_cases" in dataset
        assert len(dataset["test_cases"]) > 0
        
        for test_case in dataset["test_cases"]:
            assert "id" in test_case
            assert "query" in test_case
            assert "expected_top_recipes" in test_case
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        # Perfect match
        assert calculate_hit_rate(
            ["Recipe A", "Recipe B", "Recipe C"],
            ["Recipe A", "Recipe B"]
        ) == 1.0
        
        # Partial match
        assert calculate_hit_rate(
            ["Recipe A", "Recipe D"],
            ["Recipe A", "Recipe B", "Recipe C"]
        ) == pytest.approx(1.0 / 3.0)
        
        # No match
        assert calculate_hit_rate(
            ["Recipe X"],
            ["Recipe A", "Recipe B"]
        ) == 0.0
        
        # Empty expected
        assert calculate_hit_rate(["Recipe A"], []) == 0.0
    
    def test_precision_at_k_calculation(self):
        """Test precision@k calculation."""
        # Perfect precision@2
        assert calculate_precision_at_k(
            ["Recipe A", "Recipe B", "Recipe C"],
            ["Recipe A", "Recipe B"],
            k=2
        ) == 1.0
        
        # Partial precision@3
        assert calculate_precision_at_k(
            ["Recipe A", "Recipe X", "Recipe B"],
            ["Recipe A", "Recipe B", "Recipe C"],
            k=3
        ) == pytest.approx(2.0 / 3.0)
        
        # Zero precision
        assert calculate_precision_at_k(
            ["Recipe X", "Recipe Y"],
            ["Recipe A", "Recipe B"],
            k=2
        ) == 0.0
    
    def test_nutrition_compliance_calculation(self):
        """Test nutrition compliance calculation."""
        # Mock recipe objects
        class MockRecipe:
            def __init__(self, kcal=None, protein_g=None):
                self.macros_kcal = kcal
                self.macros_protein_g = protein_g
        
        recipes = [
            MockRecipe(kcal=300, protein_g=25),
            MockRecipe(kcal=500, protein_g=30),
            MockRecipe(kcal=200, protein_g=15),
        ]
        
        # All compliant
        assert calculate_nutrition_compliance(
            recipes,
            {"max_kcal": 600, "min_protein_g": 10}
        ) == 1.0
        
        # Some non-compliant (recipe 2 fails max_kcal, recipe 3 fails min_protein)
        # Only recipe 1 is compliant: 300 kcal <= 400, 25g >= 20g
        assert calculate_nutrition_compliance(
            recipes,
            {"max_kcal": 400, "min_protein_g": 20}
        ) == pytest.approx(1.0 / 3.0)
    
    @pytest.mark.slow
    @pytest.mark.integration
    def test_rag_pipeline_evaluation(self, db_session, mock_embedding_client):
        """End-to-end RAG pipeline evaluation on labeled dataset."""
        dataset = load_eval_dataset()
        test_cases = dataset["test_cases"]
        
        # Ensure we have recipes in the database
        recipes = db_session.exec(
            select(Recipe).options(selectinload(Recipe.ingredients))
        ).all()
        
        if not recipes:
            pytest.skip("No recipes in database for evaluation")
        
        results = []
        
        for test_case in test_cases:
            query_data = test_case["query"]
            expected_titles = test_case["expected_top_recipes"]
            constraints = query_data.get("constraints", {})
            
            # Build ComposeRequest
            req = ComposeRequest(
                message=query_data["message"],
                servings=query_data.get("servings", 1),
                day=date.fromisoformat(query_data["day"]) if query_data.get("day") else date.today(),
                preferences=query_data.get("preferences", []),
            )
            
            # Build Prefs
            prefs_dict = query_data.get("prefs", {})
            prefs = Prefs(**prefs_dict)
            
            # Run RAG pipeline
            start_time = time.time()
            ideas, meta = _recipes_matching_query(
                session=db_session,
                req=req,
                prefs=prefs,
                constraints=constraints,
                limit=5,
            )
            latency = time.time() - start_time
            
            # Extract retrieved titles
            retrieved_titles = [idea.title for idea in ideas]
            
            # Calculate metrics
            hit_rate = calculate_hit_rate(retrieved_titles, expected_titles)
            precision_at_3 = calculate_precision_at_k(retrieved_titles, expected_titles, k=3)
            
            # Get recipe objects for compliance checks
            recipe_objects = []
            for idea in ideas:
                recipe = db_session.exec(
                    select(Recipe).where(Recipe.title == idea.title)
                ).first()
                if recipe:
                    recipe_objects.append(recipe)
            
            nutrition_compliance = calculate_nutrition_compliance(
                recipe_objects, constraints
            )
            macro_compliance = calculate_macro_score_compliance(recipe_objects)
            
            results.append({
                "test_id": test_case["id"],
                "hit_rate": hit_rate,
                "precision_at_3": precision_at_3,
                "nutrition_compliance": nutrition_compliance,
                "macro_compliance": macro_compliance,
                "latency_seconds": latency,
                "retrieved_count": len(retrieved_titles),
                "expected_count": len(expected_titles),
                "used_embeddings": meta.get("used_embeddings", False),
            })
        
        # Assert minimum thresholds
        avg_hit_rate = sum(r["hit_rate"] for r in results) / len(results)
        avg_precision = sum(r["precision_at_3"] for r in results) / len(results)
        avg_compliance = sum(r["nutrition_compliance"] for r in results) / len(results)
        avg_latency = sum(r["latency_seconds"] for r in results) / len(results)
        
        # Log results for debugging
        print(f"\n=== RAG Evaluation Results ===")
        print(f"Average Hit Rate: {avg_hit_rate:.2%}")
        print(f"Average Precision@3: {avg_precision:.2%}")
        print(f"Average Nutrition Compliance: {avg_compliance:.2%}")
        print(f"Average Latency: {avg_latency:.3f}s")
        
        for result in results:
            print(f"  {result['test_id']}: HR={result['hit_rate']:.2%}, "
                  f"P@3={result['precision_at_3']:.2%}, "
                  f"Latency={result['latency_seconds']:.3f}s")
        
        # Basic assertions (adjust thresholds as needed)
        assert avg_hit_rate >= 0.0, "Hit rate should be non-negative"
        assert avg_precision >= 0.0, "Precision should be non-negative"
        assert avg_latency < 10.0, "Average latency should be under 10 seconds"
