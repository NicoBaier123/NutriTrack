#!/usr/bin/env python3
"""Add fiber columns to food and recipe tables if they do not exist."""

import sqlite3
from pathlib import Path

DB_PATHS = [
    Path(__file__).resolve().parent.parent / "dbwdi.db",
    Path(__file__).resolve().parent.parent.parent / "dbwdi.db",
]


def locate_db() -> Path:
    for candidate in DB_PATHS:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not locate dbwdi.db. Looked in: {[str(p) for p in DB_PATHS]}")


def column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def add_column(cursor: sqlite3.Cursor, table: str, column: str, ddl: str) -> None:
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def main() -> None:
    db_path = locate_db()
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    print(f"Using database: {db_path}")

    # Add fiber column to food (grams per 100g)
    if not column_exists(cur, "food", "fiber_g"):
        print("Adding fiber_g column to food table …")
        add_column(cur, "food", "fiber_g", "REAL DEFAULT 0.0")
    else:
        print("fiber_g column already present on food table")

    # Add macros_fiber to recipe table (per serving)
    if not column_exists(cur, "recipe", "macros_fiber_g"):
        print("Adding macros_fiber_g column to recipe table …")
        add_column(cur, "recipe", "macros_fiber_g", "REAL")
    else:
        print("macros_fiber_g column already present on recipe table")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    main()
