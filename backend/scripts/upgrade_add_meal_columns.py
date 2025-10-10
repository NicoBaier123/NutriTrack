# backend/scripts/upgrade_add_meal_columns.py
import sqlite3, os

DB = os.environ.get("DATABASE_URL_SQLITE", "./nutritrack.db")
conn = sqlite3.connect(DB)
cur = conn.cursor()

def col_exists(table, col):
    cur.execute(f"PRAGMA table_info({table});")
    return any(r[1] == col for r in cur.fetchall())

def idx_exists(name):
    cur.execute("PRAGMA index_list(meal);")
    return any(r[1] == name for r in cur.fetchall())

alters = []
if not col_exists("meal", "source"):
    alters.append("ALTER TABLE meal ADD COLUMN source TEXT;")
if not col_exists("meal", "input_text"):
    alters.append("ALTER TABLE meal ADD COLUMN input_text TEXT;")
if not col_exists("meal", "import_hash"):
    # Wichtig: OHNE UNIQUE anlegen, UNIQUE kommt als Index
    alters.append("ALTER TABLE meal ADD COLUMN import_hash TEXT;")
if not col_exists("meal", "created_at"):
    alters.append("ALTER TABLE meal ADD COLUMN created_at TIMESTAMP;")

for stmt in alters:
    print("RUN:", stmt)
    cur.execute(stmt)

# UNIQUE-Index für import_hash (mehrere NULLs erlaubt in SQLite)
if not idx_exists("ux_meal_import_hash"):
    print("RUN: CREATE UNIQUE INDEX IF NOT EXISTS ux_meal_import_hash ON meal(import_hash);")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_meal_import_hash ON meal(import_hash);")

conn.commit()
conn.close()
print("Done.")
