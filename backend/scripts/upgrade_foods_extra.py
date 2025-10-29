# backend/scripts/upgrade_foods_extra.py
import os, sqlite3

DB = os.environ.get("DATABASE_URL_SQLITE", "./dbwdi.db")
conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS foodsynonym (
  id INTEGER PRIMARY KEY,
  food_id INTEGER NOT NULL,
  synonym TEXT,
  FOREIGN KEY(food_id) REFERENCES food(id)
);
""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_foodsynonym_food ON foodsynonym(food_id);")
cur.execute("CREATE INDEX IF NOT EXISTS ix_foodsynonym_syn ON foodsynonym(synonym);")

cur.execute("""
CREATE TABLE IF NOT EXISTS foodpending (
  id INTEGER PRIMARY KEY,
  original_name TEXT,
  cleaned_name TEXT,
  top_suggestion TEXT,
  top_score REAL,
  created_at TIMESTAMP
);
""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_foodpending_created ON foodpending(created_at);")

cur.execute("""
CREATE TABLE IF NOT EXISTS foodsource (
  id INTEGER PRIMARY KEY,
  food_id INTEGER NOT NULL,
  source TEXT,
  source_id TEXT,
  acquired_at TIMESTAMP,
  FOREIGN KEY(food_id) REFERENCES food(id)
);
""")
cur.execute("CREATE INDEX IF NOT EXISTS ix_foodsource_food ON foodsource(food_id);")
cur.execute("CREATE INDEX IF NOT EXISTS ix_foodsource_pair ON foodsource(source, source_id);")

conn.commit()
conn.close()
print("Done.")
