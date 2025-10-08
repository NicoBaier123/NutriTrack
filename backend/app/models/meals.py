from typing import Optional, List
from datetime import date
from sqlmodel import SQLModel, Field, Relationship

class Meal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    # optional: breakfast/lunch/dinner/snack
    type: Optional[str] = Field(default=None, index=True)
    items: List["MealItem"] = Relationship(
        back_populates="meal", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

class MealItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    meal_id: int = Field(foreign_key="meal.id", index=True)
    food_id: int = Field(foreign_key="food.id", index=True)
    grams: float = 0.0

    meal: Meal = Relationship(back_populates="items")
