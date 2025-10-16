from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select, SQLModel
from app.db import get_session
from app.models.foods import Food

router = APIRouter(prefix="/foods", tags=["foods"])

class FoodDetailOut(SQLModel):
    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float

@router.get("/search", response_model=List[str], summary="Foods suchen (case-insensitive)")
def search_foods(
    q: Optional[str] = Query(default="", min_length=0),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(Food.name).order_by(Food.name.asc()).limit(limit).offset(offset)
    if q:
        like = f"%{q.strip()}%"
        stmt = (
            select(Food.name)
            .where(func.lower(Food.name).like(func.lower(like)))
            .order_by(Food.name.asc())
            .limit(limit).offset(offset)
        )
    rows = session.exec(stmt).all()
    return [r if isinstance(r, str) else r[0] for r in rows]

@router.get("/detail", response_model=FoodDetailOut, summary="Nährwerte (exakter Name)")
def food_detail(name: str, session: Session = Depends(get_session)):
    food = session.exec(select(Food).where(Food.name == name)).first()
    if not food:
        raise HTTPException(404, "Food not found")
    return FoodDetailOut(
        name=food.name,
        kcal=float(food.kcal),
        protein_g=float(food.protein_g),
        carbs_g=float(food.carbs_g),
        fat_g=float(food.fat_g),
    )
