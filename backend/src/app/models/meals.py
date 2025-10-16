# backend/app/models/meals.py
from typing import Optional, List
from datetime import date, datetime
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship

class MealType(str, Enum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"

class Meal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    type: Optional[MealType] = Field(default=None, index=True)

    # Herkunft & Nachvollziehbarkeit
    source: Optional[str] = Field(default="manual", index=True)
    input_text: Optional[str] = None

    # Idempotenz-Hash – Eindeutigkeit kommt über den DB-Index aus dem Upgrade-Script
    import_hash: Optional[str] = Field(default=None)

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    items: List["MealItem"] = Relationship(
        back_populates="meal",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class MealItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id", index=True)
    food_id: int = Field(foreign_key="food.id", index=True)
    grams: float = 0.0

    meal: Meal = Relationship(back_populates="items")
