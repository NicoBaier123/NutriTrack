from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class MacroTotals(BaseModel):
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0
    fiber_g: float = 0.0


class GapsResponse(BaseModel):
    day: date
    target: Optional[MacroTotals] = None
    intake: MacroTotals
    remaining: Optional[MacroTotals] = None
    notes: List[str] = []


class SuggestionItem(BaseModel):
    food: str
    grams: float


class Suggestion(BaseModel):
    name: str
    items: List[SuggestionItem]
    source: Literal["db", "llm", "cookbook", "rag", "fallback"] = "db"
    est_kcal: Optional[float] = None
    est_protein_g: Optional[float] = None
    est_carbs_g: Optional[float] = None
    est_fat_g: Optional[float] = None
    est_fiber_g: Optional[float] = None


class RecommendationsResponse(BaseModel):
    day: date
    remaining: MacroTotals
    mode: Literal["db", "open", "rag", "hybrid"]
    suggestions: List[Suggestion]


class Prefs(BaseModel):
    veggie: Optional[bool] = None
    vegan: Optional[bool] = None
    no_pork: Optional[bool] = None
    lactose_free: Optional[bool] = None
    gluten_free: Optional[bool] = None
    allergens_avoid: Optional[List[str]] = None
    budget_level: Optional[Literal["low", "mid", "high"]] = None
    cuisine_bias: Optional[List[str]] = None


class Macro(BaseModel):
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: Optional[float] = None


class Ingredient(BaseModel):
    name: str
    grams: Optional[float] = None
    note: Optional[str] = None


class RecipeIdea(BaseModel):
    title: str
    time_minutes: Optional[int] = None
    difficulty: Optional[Literal["easy", "medium", "hard"]] = "easy"
    ingredients: List[Ingredient] = Field(default_factory=list)
    instructions: List[str]
    macros: Optional[Macro] = None
    tags: List[str] = []
    source: Literal["rag", "llm", "fallback", "db"] = "rag"


class ComposeRequest(BaseModel):
    message: str = Field(..., description="Freitext: z.B. 'proteinreiches Abendessen <800 kcal, vegetarisch'")
    day: Optional[date] = None
    body_weight_kg: Optional[float] = None
    servings: int = 1
    preferences: List[str] = []


class ComposeResponse(BaseModel):
    constraints: Dict[str, Any]
    ideas: List[RecipeIdea]
    notes: List[str] = []


class ChatRequest(BaseModel):
    message: str = Field(..., description="Benutzereingabe (Frage/Aufgabe)")
    context: Optional[str] = Field(
        default=None,
        description="Optional: zusätzlicher Kontext (z.B. Tagesdaten, Ziele, Praeferenzen).",
    )
    json_mode: bool = Field(
        False, description="Wenn true, bitte strikt JSON zurückgeben (z.B. für Tools)."
    )


class ChatResponse(BaseModel):
    output: str
    used_backend: Literal["llama_cpp", "ollama_http", "ollama_cli"] = "ollama_http"

