#!/usr/bin/env python3
"""
RAG Evaluation Script

Loads labeled dataset, runs modular RAG pipeline, calculates KPIs, and prints summary table.

Usage:
    python scripts/run_rag_eval.py
"""
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import date

# Add src to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from sqlmodel import Session, select
from sqlalchemy.orm import selectinload

from app.core.database import engine
from app.models.recipes import Recipe
from app.routers.advisor.rag import _recipes_matching_query
from app.routers.advisor.schemas import ComposeRequest, Prefs

# Import metric functions from test module
sys.path.insert(0, str(PROJECT_ROOT / "tests"))
from rag_metrics_test import (
    load_eval_dataset,
    calculate_hit_rate,
    calculate_precision_at_k,
    calculate_nutrition_compliance,
    calculate_macro_score_compliance,
)

# Load evaluation dataset
EVAL_DATA_PATH = PROJECT_ROOT / "tests" / "data" / "rag_eval.json"


def format_table_row(values: List[Any], widths: List[int]) -> str:
    """Format a table row with specified column widths."""
    return " | ".join(str(val).ljust(width) for val, width in zip(values, widths))


def print_summary_table(results: List[Dict[str, Any]]):
    """Print a formatted summary table of evaluation results."""
    if not results:
        print("No results to display.")
        return
    
    # Calculate aggregate metrics
    avg_hit_rate = sum(r["hit_rate"] for r in results) / len(results)
    avg_precision = sum(r["precision_at_3"] for r in results) / len(results)
    avg_compliance = sum(r["nutrition_compliance"] for r in results) / len(results)
    avg_macro_compliance = sum(r["macro_compliance"] for r in results) / len(results)
    avg_latency = sum(r["latency_seconds"] for r in results) / len(results)
    total_embeddings_used = sum(1 for r in results if r["used_embeddings"])
    
    # Define column headers and widths
    headers = ["Test ID", "Hit Rate", "P@3", "Nutr. Comp.", "Macro Comp.", "Latency (s)", "Embed?"]
    widths = [12, 10, 8, 12, 12, 12, 8]
    
    print("\n" + "=" * 90)
    print("RAG EVALUATION SUMMARY".center(90))
    print("=" * 90)
    print(format_table_row(headers, widths))
    print("-" * 90)
    
    # Print individual test results
    for result in results:
        row = [
            result["test_id"],
            f"{result['hit_rate']:.2%}",
            f"{result['precision_at_3']:.2%}",
            f"{result['nutrition_compliance']:.2%}",
            f"{result['macro_compliance']:.2%}",
            f"{result['latency_seconds']:.3f}",
            "Yes" if result["used_embeddings"] else "No",
        ]
        print(format_table_row(row, widths))
    
    print("-" * 90)
    
    # Print aggregate metrics
    agg_row = [
        "AVERAGE",
        f"{avg_hit_rate:.2%}",
        f"{avg_precision:.2%}",
        f"{avg_compliance:.2%}",
        f"{avg_macro_compliance:.2%}",
        f"{avg_latency:.3f}",
        f"{total_embeddings_used}/{len(results)}",
    ]
    print(format_table_row(agg_row, widths))
    print("=" * 90)
    
    # Print detailed statistics
    print("\n=== Aggregate KPIs ===")
    print(f"Average Hit Rate:        {avg_hit_rate:.2%}")
    print(f"Average Precision@3:     {avg_precision:.2%}")
    print(f"Average Nutrition Compliance: {avg_compliance:.2%}")
    print(f"Average Macro Compliance: {avg_macro_compliance:.2%}")
    print(f"Average Response Latency: {avg_latency:.3f} seconds")
    print(f"Embeddings Used:         {total_embeddings_used}/{len(results)} tests")
    print(f"Total Test Cases:        {len(results)}")
    
    # Per-test-case details
    print("\n=== Per-Test-Case Details ===")
    for result in results:
        print(f"\n{result['test_id']}:")
        print(f"  Retrieved: {result['retrieved_count']} recipes")
        print(f"  Expected:  {result['expected_count']} recipes")
        print(f"  Hit Rate:  {result['hit_rate']:.2%}")
        print(f"  Precision@3: {result['precision_at_3']:.2%}")
        print(f"  Latency:   {result['latency_seconds']:.3f}s")
        if result.get('retrieved_titles'):
            print(f"  Retrieved Titles: {', '.join(result['retrieved_titles'][:3])}...")
        if result.get('expected_titles'):
            print(f"  Expected Titles:  {', '.join(result['expected_titles'])}")


def run_evaluation() -> List[Dict[str, Any]]:
    """Run RAG evaluation on labeled dataset."""
    # Load dataset
    print(f"Loading evaluation dataset from {EVAL_DATA_PATH}...")
    dataset = load_eval_dataset()
    test_cases = dataset["test_cases"]
    print(f"Loaded {len(test_cases)} test cases.")
    
    # Open database session
    print("Connecting to database...")
    with Session(engine) as session:
        # Check if recipes exist
        recipes = session.exec(
            select(Recipe).options(selectinload(Recipe.ingredients))
        ).all()
        
        if not recipes:
            print("WARNING: No recipes found in database. Evaluation will be limited.")
            print("Run seed_smoothie_bowls.py or ensure recipes are loaded.")
        else:
            print(f"Found {len(recipes)} recipes in database.")
        
        results = []
        
        print("\nRunning evaluation...")
        for idx, test_case in enumerate(test_cases, 1):
            test_id = test_case["id"]
            query_data = test_case["query"]
            expected_titles = test_case["expected_top_recipes"]
            constraints = query_data.get("constraints", {})
            
            print(f"  [{idx}/{len(test_cases)}] Processing {test_id}...", end=" ", flush=True)
            
            try:
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
                    session=session,
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
                    recipe = session.exec(
                        select(Recipe).where(Recipe.title == idea.title)
                    ).first()
                    if recipe:
                        recipe_objects.append(recipe)
                
                nutrition_compliance = calculate_nutrition_compliance(
                    recipe_objects, constraints
                )
                macro_compliance = calculate_macro_score_compliance(recipe_objects)
                
                result = {
                    "test_id": test_id,
                    "hit_rate": hit_rate,
                    "precision_at_3": precision_at_3,
                    "nutrition_compliance": nutrition_compliance,
                    "macro_compliance": macro_compliance,
                    "latency_seconds": latency,
                    "retrieved_count": len(retrieved_titles),
                    "expected_count": len(expected_titles),
                    "used_embeddings": meta.get("used_embeddings", False),
                    "retrieved_titles": retrieved_titles,
                    "expected_titles": expected_titles,
                }
                results.append(result)
                
                print(f"[OK] (HR={hit_rate:.2%}, P@3={precision_at_3:.2%}, {latency:.3f}s)")
                
            except Exception as e:
                print(f"[ERROR] {e}")
                results.append({
                    "test_id": test_id,
                    "hit_rate": 0.0,
                    "precision_at_3": 0.0,
                    "nutrition_compliance": 0.0,
                    "macro_compliance": 0.0,
                    "latency_seconds": 0.0,
                    "retrieved_count": 0,
                    "expected_count": len(expected_titles),
                    "used_embeddings": False,
                    "error": str(e),
                })
    
    return results


def main():
    """Main entry point for evaluation script."""
    print("=" * 90)
    print("RAG Evaluation Script".center(90))
    print("=" * 90)
    
    try:
        results = run_evaluation()
        print_summary_table(results)
        
        # Exit with appropriate code
        avg_hit_rate = sum(r["hit_rate"] for r in results) / len(results) if results else 0.0
        if avg_hit_rate > 0.0:
            print("\n[SUCCESS] Evaluation completed successfully.")
            sys.exit(0)
        else:
            print("\n[FAILED] Evaluation completed with zero hit rate.")
            sys.exit(1)
            
    except FileNotFoundError as e:
        print(f"\n[ERROR] Evaluation dataset not found: {e}")
        print(f"Expected path: {EVAL_DATA_PATH}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Evaluation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
