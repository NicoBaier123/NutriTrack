#!/usr/bin/env python3
"""
Migration script to add the food.fiber_g column if it is missing.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Optional


def column_exists(cursor: sqlite3.Cursor, table: str, column: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cursor.fetchall())


def resolve_sqlite_path() -> Path:
    """Return the sqlite database path using the FastAPI settings."""
    project_root = Path(__file__).resolve().parents[2]
    src_dir = project_root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))

    try:
        from app.core.config import get_settings  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - defensive
        raise SystemExit("Unable to import app.core.config; ensure PYTHONPATH includes backend/src.") from exc

    settings = get_settings()
    db_url = settings.database_url

    if not db_url.startswith("sqlite"):
        raise SystemExit(f"Unsupported database URL for this migration: {db_url}")

    # Handle urls of form sqlite:///absolute/path or sqlite:///relative/path.
    # Strip the leading 'sqlite:///' (three slashes) or 'sqlite://' cases.
    path_part: Optional[str] = None
    if db_url.startswith("sqlite:///"):
        path_part = db_url[len("sqlite:///") :]
    elif db_url.startswith("sqlite://"):
        path_part = db_url[len("sqlite://") :]

    if not path_part:
        raise SystemExit(f"Could not determine filesystem path from database URL: {db_url}")

    db_path = Path(path_part)
    if not db_path.is_absolute():
        db_path = (project_root / db_path).resolve()

    return db_path


def main() -> None:
    db_path = resolve_sqlite_path()

    if not db_path.exists():
        raise SystemExit(f"Database not found at {db_path}. Run migrations after initializing the DB.")

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    print(f"[MIGRATE] Checking for food.fiber_g column in {db_path}")

    if column_exists(cursor, "food", "fiber_g"):
        print("[SKIP] Column fiber_g already exists on food table.")
    else:
        print("[APPLY] Adding fiber_g column to food table...")
        cursor.execute("ALTER TABLE food ADD COLUMN fiber_g REAL DEFAULT 0.0")
        conn.commit()
        print("[DONE] Column fiber_g added.")

    conn.close()


if __name__ == "__main__":
    main()

