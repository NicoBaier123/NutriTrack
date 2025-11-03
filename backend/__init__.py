from __future__ import annotations

import sys
from pathlib import Path


def _candidate_paths() -> list[str]:
    """Return folders that should expose backend.* subpackages."""
    base_dir = Path(__file__).resolve().parent
    candidates = [base_dir, base_dir / "src"]

    # Include optional extras (e.g. tests) if present so backend.tests.* still works.
    tests_dir = base_dir / "tests"
    if tests_dir.is_dir():
        candidates.append(tests_dir)

    return [str(path) for path in candidates if path.is_dir()]


__path__ = _candidate_paths()

for path in __path__:
    if path not in sys.path:
        sys.path.insert(0, path)
