#!/usr/bin/env python3
"""Inspect dbwdi.db database and show tables, including recipe_embeddings."""
import sqlite3
import sys
from pathlib import Path

# Try to find the database
db_paths = [
    Path(__file__).parent / "dbwdi.db",  # backend/dbwdi.db
    Path(__file__).parent.parent / "dbwdi.db",  # root/dbwdi.db
]

db_path = None
for path in db_paths:
    if path.exists():
        db_path = path
        break

if not db_path:
    print("ERROR: Could not find dbwdi.db in expected locations")
    print(f"Looked in: {[str(p) for p in db_paths]}")
    sys.exit(1)

print(f"Opening database: {db_path.absolute()}")
print("=" * 60)

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Get all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cursor.fetchall()

print(f"\nTotal tables: {len(tables)}")
print("\nTables in database:")
for table in tables:
    print(f"  - {table[0]}")

# Check for recipe_embeddings
print("\n" + "=" * 60)
if any(t[0] == "recipe_embeddings" for t in tables):
    print("[OK] recipe_embeddings table EXISTS!")
    
    cursor.execute("SELECT COUNT(*) FROM recipe_embeddings")
    count = cursor.fetchone()[0]
    print(f"   Cached embeddings: {count}")
    
    if count > 0:
        # Show first few entries
        cursor.execute("""
            SELECT recipe_id, model_name, updated_at, 
                   json_array_length(embedding) as embedding_size
            FROM recipe_embeddings 
            LIMIT 5
        """)
        rows = cursor.fetchall()
        print("\n   Sample entries:")
        for row in rows:
            recipe_id, model, updated, emb_size = row
            print(f"     Recipe ID {recipe_id}: {emb_size} dimensions, model={model}, updated={updated}")
else:
    print("[WARNING] recipe_embeddings table does NOT exist yet")
    print("   (It will be created automatically when first recipe is embedded)")

# Check for recipe table
print("\n" + "=" * 60)
if any(t[0] == "recipe" for t in tables):
    cursor.execute("SELECT COUNT(*) FROM recipe")
    recipe_count = cursor.fetchone()[0]
    print(f"[OK] recipe table exists with {recipe_count} recipes")
else:
    print("[WARNING] recipe table does not exist")

conn.close()
print("\n" + "=" * 60)
print("To view database in a GUI:")
print("  1. DB Browser for SQLite (free): https://sqlitebrowser.org/")
print("  2. VS Code Extension: SQLite Viewer")
print("  3. Online: https://sqliteviewer.app/")
