#!/usr/bin/env python3
"""Add macros_fiber_g column to recipe table if it is missing.

This migration is idempotent: running it multiple times is safe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "dbwdi.db"


def column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def main() -> None:
    if not DB_PATH.exists():
        print(f"[SKIP] Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        if column_exists(cur, "recipe", "macros_fiber_g"):
            print("[OK] recipe.macros_fiber_g already exists")
            return

        print("[MIGRATE] Adding recipe.macros_fiber_g column")
        cur.execute("ALTER TABLE recipe ADD COLUMN macros_fiber_g REAL")
        conn.commit()
        print("[DONE] Column macros_fiber_g added to recipe table")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
