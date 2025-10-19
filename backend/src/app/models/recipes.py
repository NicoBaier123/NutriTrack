from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


class Recipe(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    source: str = Field(default="llm", index=True)
    request_message: Optional[str] = None
    request_day: Optional[date] = Field(default=None, index=True)
    request_servings: Optional[int] = None
    preferences_json: Optional[str] = None
    constraints_json: Optional[str] = None
    instructions_json: Optional[List[str]] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
    notes: Optional[str] = None
    time_minutes: Optional[int] = None
    difficulty: Optional[str] = Field(default=None, index=True)
    tags: Optional[str] = Field(default=None, index=True, description="Comma separated tags")
    macros_kcal: Optional[float] = None
    macros_protein_g: Optional[float] = None
    macros_carbs_g: Optional[float] = None
    macros_fat_g: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    ingredients: List["RecipeItem"] = Relationship(
        back_populates="recipe",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class RecipeItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    recipe_id: int = Field(foreign_key="recipe.id", index=True)
    name: str = Field(index=True)
    grams: Optional[float] = None
    note: Optional[str] = None

    recipe: Recipe = Relationship(back_populates="ingredients")
