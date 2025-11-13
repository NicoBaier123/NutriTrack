#!/usr/bin/env python3
"""Check RAG system state in database."""
from sqlmodel import Session, select
from app.core.database import engine
from app.models.recipes import Recipe

print("=== RAG System State Check ===")

with Session(engine) as session:
    # Check recipes
    recipes = session.exec(select(Recipe)).all()
    print(f"\nTotal recipes in database: {len(recipes)}")
    
    # Check if recipe_embeddings table exists
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    if "recipe_embeddings" in tables:
        print("\n[OK] recipe_embeddings table exists")
        from app.rag.indexer import RecipeIndexer, RecipeEmbedding
        indexer = RecipeIndexer(session)
        count = indexer.get_cached_count()
        print(f"  Cached embeddings: {count}")
        
        # List first few recipes with embedding status
        print("\nEmbedding cache status:")
        for recipe in recipes[:10]:
            emb = indexer.get_embedding(recipe.id)
            status = "[CACHED]" if emb else "[NOT CACHED]"
            print(f"  {recipe.id}: {recipe.title[:40]:40} - {status}")
    else:
        print("\n[WARNING] recipe_embeddings table does NOT exist")
        print("  This means embeddings haven't been cached yet.")
        print("  The table will be created on first embedding computation.")
