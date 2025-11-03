#!/usr/bin/env python
"""
Script to setup and seed the database for RAG functionality.
Run this script from the project root to initialize the database with recipes.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add backend/src to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

from app.core.database import engine, init_db
from app.models.foods import Food
from app.models.recipes import Recipe
from sqlmodel import Session, select

def init_and_seed():
    """Initialize database and seed with sample recipes."""
    print("Initializing database...")
    init_db()
    
    print("Checking existing data...")
    with Session(engine) as session:
        food_count = len(session.exec(select(Food)).all())
        recipe_count = len(session.exec(select(Recipe)).all())
        print(f"Current counts - Foods: {food_count}, Recipes: {recipe_count}")
        
        # If we already have recipes, don't seed again
        if recipe_count > 0:
            print("Database already seeded with recipes. Skipping...")
            return
    
    print("Seeding database with recipes...")
    # Run the seed script
    from backend.scripts.seed_smoothie_bowls import main as seed_main
    seed_main()
    
    print("Database setup complete!")
    with Session(engine) as session:
        food_count = len(session.exec(select(Food)).all())
        recipe_count = len(session.exec(select(Recipe)).all())
        print(f"Final counts - Foods: {food_count}, Recipes: {recipe_count}")

if __name__ == "__main__":
    try:
        init_and_seed()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

