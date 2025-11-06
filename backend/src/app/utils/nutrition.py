from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass
class Macros:
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "kcal": float(self.kcal),
            "protein_g": float(self.protein_g),
            "carbs_g": float(self.carbs_g),
            "fat_g": float(self.fat_g),
            "fiber_g": float(self.fiber_g),
        }


def macros_for_grams(
    kcal_100g: Optional[float],
    protein_g_100g: Optional[float],
    carbs_g_100g: Optional[float],
    fat_g_100g: Optional[float],
    fiber_g_100g: Optional[float],
    grams: float,
) -> Macros:
    """Compute macros for a given grams amount from per-100g values.

    - Treat None or NaN as 0.0
    - Negative grams are clamped to 0
    """
    g = max(0.0, float(grams or 0.0))
    factor = g / 100.0

    def f(x: Optional[float]) -> float:
        try:
            return float(x or 0.0)
        except Exception:
            return 0.0

    return Macros(
        kcal=f(kcal_100g) * factor,
        protein_g=f(protein_g_100g) * factor,
        carbs_g=f(carbs_g_100g) * factor,
        fat_g=f(fat_g_100g) * factor,
        fiber_g=f(fiber_g_100g) * factor,
    )


def sum_macros(items: Iterable[Macros]) -> Macros:
    total = Macros()
    for it in items:
        total.kcal += getattr(it, "kcal", 0.0) or 0.0
        total.protein_g += getattr(it, "protein_g", 0.0) or 0.0
        total.carbs_g += getattr(it, "carbs_g", 0.0) or 0.0
        total.fat_g += getattr(it, "fat_g", 0.0) or 0.0
        total.fiber_g += getattr(it, "fiber_g", 0.0) or 0.0
    return total


def round_macros(m: Macros, ndigits: int = 1) -> Macros:
    return Macros(
        kcal=round(m.kcal, ndigits),
        protein_g=round(m.protein_g, ndigits),
        carbs_g=round(m.carbs_g, ndigits),
        fat_g=round(m.fat_g, ndigits),
        fiber_g=round(m.fiber_g, ndigits),
    )
