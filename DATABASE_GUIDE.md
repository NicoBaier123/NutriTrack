# Database Inspection Guide

## Where is the Database?

The database file is located at:
- **Primary location**: `backend/dbwdi.db`
- **Alternative location**: `dbwdi.db` (root directory)

## Where are Embeddings Stored?

Embeddings are stored in the **`recipe_embeddings`** table inside the SQLite database.

### Table Structure:

```sql
CREATE TABLE recipe_embeddings (
    recipe_id INTEGER PRIMARY KEY,  -- Foreign key to recipe.id
    embedding JSON,                  -- Array of 384 floats [0.123, -0.456, ...]
    document_text TEXT,              -- Original text used for embedding
    model_name TEXT,                 -- e.g., "all-MiniLM-L6-v2"
    updated_at TIMESTAMP             -- When embedding was created/updated
);
```

## How to View the Database

### Option 1: Python Script (Easiest)
Run the inspection script:
```bash
python backend/inspect_db.py
```

### Option 2: DB Browser for SQLite (GUI - Recommended)
1. Download: https://sqlitebrowser.org/ (free, open-source)
2. Install and open
3. Click "Open Database"
4. Navigate to `backend/dbwdi.db`
5. Browse tables, including `recipe_embeddings`

### Option 3: VS Code Extension
1. Install "SQLite Viewer" extension in VS Code
2. Right-click on `backend/dbwdi.db`
3. Select "Open Database" or "View Database"

### Option 4: Command Line (SQLite CLI)
```bash
# Install SQLite (usually pre-installed on Linux/Mac)
# Windows: Download from https://www.sqlite.org/download.html

sqlite3 backend/dbwdi.db

# Then run:
.tables                           # List all tables
SELECT * FROM recipe_embeddings;  # View embeddings
.schema recipe_embeddings         # Show table structure
```

### Option 5: Online Viewer
1. Go to: https://sqliteviewer.app/
2. Upload `backend/dbwdi.db`
3. Browse tables

## Quick SQL Queries

### View all tables:
```sql
SELECT name FROM sqlite_master WHERE type='table';
```

### Count cached embeddings:
```sql
SELECT COUNT(*) FROM recipe_embeddings;
```

### View embeddings for recipe ID 5:
```sql
SELECT recipe_id, model_name, updated_at, 
       json_array_length(embedding) as vector_size
FROM recipe_embeddings
WHERE recipe_id = 5;
```

### View all recipes with their embeddings:
```sql
SELECT r.id, r.title, 
       CASE WHEN re.recipe_id IS NOT NULL THEN 'YES' ELSE 'NO' END as has_embedding
FROM recipe r
LEFT JOIN recipe_embeddings re ON r.id = re.recipe_id;
```

## Understanding the Embedding Data

Each embedding is a **JSON array of 384 floating-point numbers**, like:
```json
[0.123, -0.456, 0.789, ..., -0.234]
```

These represent the semantic meaning of the recipe text in a 384-dimensional space.

## Troubleshooting

### "Table recipe_embeddings doesn't exist"
- **Normal**: Table is created automatically on first use
- **Fix**: Run a RAG query that uses embeddings, and the table will be created

### "Can't find dbwdi.db"
- Check `backend/dbwdi.db` first (this is the active one)
- If missing, check root directory: `dbwdi.db`
- The app uses `backend/dbwdi.db` (see `backend/src/app/core/config.py`)

### "Database is locked"
- Close any other programs viewing the database
- Restart the FastAPI server
- Try again

## Example: View Embeddings in Python

```python
import sqlite3
import json

conn = sqlite3.connect('backend/dbwdi.db')
cursor = conn.cursor()

# Get embedding for recipe ID 1
cursor.execute("SELECT embedding FROM recipe_embeddings WHERE recipe_id = 1")
row = cursor.fetchone()

if row:
    embedding = json.loads(row[0])
    print(f"Vector dimensions: {len(embedding)}")
    print(f"First 5 values: {embedding[:5]}")
else:
    print("No embedding found for recipe ID 1")

conn.close()
```
