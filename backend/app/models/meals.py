from typing import Optional, List
from datetime import date
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
    type: Optional[MealType] = Field(default=None, index=True)  # Enum als String gespeichert
    items: List["MealItem"] = Relationship(
        back_populates="meal", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class MealItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id", index=True)
    food_id: int = Field(foreign_key="food.id", index=True)
    grams: float = 0.0

    meal: Meal = Relationship(back_populates="items")
