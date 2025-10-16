# backend/app/models/foods_extra.py
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field

class FoodSynonym(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    food_id: int = Field(foreign_key="food.id", index=True)
    synonym: str = Field(index=True)

class FoodPending(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    original_name: str
    cleaned_name: str
    top_suggestion: Optional[str] = None
    top_score: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)

class FoodSource(SQLModel, table=True):
    """Provenienz für automatisch angelegte Foods."""
    id: Optional[int] = Field(default=None, primary_key=True)
    food_id: int = Field(foreign_key="food.id", index=True)
    source: str = Field(index=True)      # "fdc" | "off" | "manual"
    source_id: str = Field(index=True)   # z.B. FDC-ID, Barcode
    acquired_at: datetime = Field(default_factory=datetime.utcnow, index=True)
