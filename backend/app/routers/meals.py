from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from datetime import date
from sqlmodel import Session, select, func
from ..db import get_session
from ..models.meals import Meal, MealItem
from ..models.foods import Food

router = APIRouter(prefix="/meals", tags=["meals"])

@router.post("/item", status_code=201)
def add_meal_item(
    day: date,
    food_name: str,
    grams: float = Query(..., gt=0),
    type: Optional[str] = None,
    session: Session = Depends(get_session),
):
    food = session.exec(select(Food).where(Food.name == food_name)).first()
    if not food:
        raise HTTPException(404, f"Food '{food_name}' not found")

    meal_stmt = select(Meal).where(Meal.day == day)
    meal_stmt = meal_stmt.where(Meal.type == type) if type is not None else meal_stmt.where(Meal.type.is_(None))
    meal = session.exec(meal_stmt).first()

    if not meal:
        meal = Meal(day=day, type=type)
        session.add(meal)
        session.flush()  # erhält meal.id

    item = MealItem(meal_id=meal.id, food_id=food.id, grams=grams)
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"meal_id": meal.id, "item_id": item.id, "food": food.name, "grams": grams}

@router.get("/day")
def meals_day(day: date, session: Session = Depends(get_session)):
    q = (
        select(
            Food.name.label("name"),
            func.sum(MealItem.grams).label("grams"),
            (func.sum(MealItem.grams) * Food.kcal / 100.0).label("kcal"),
            (func.sum(MealItem.grams) * Food.protein_g / 100.0).label("protein_g"),
            (func.sum(MealItem.grams) * Food.carbs_g / 100.0).label("carbs_g"),
            (func.sum(MealItem.grams) * Food.fat_g / 100.0).label("fat_g"),
        )
        .join(Meal, Meal.id == MealItem.meal_id)
        .join(Food, Food.id == MealItem.food_id)
        .where(Meal.day == day)
        .group_by(Food.id)
    )
    rows = session.exec(q).all()
    total = {
        "kcal": float(sum((r.kcal or 0) for r in rows)),
        "protein_g": float(sum((r.protein_g or 0) for r in rows)),
        "carbs_g": float(sum((r.carbs_g or 0) for r in rows)),
        "fat_g": float(sum((r.fat_g or 0) for r in rows)),
    }
    items = [
        {
            "name": r.name,
            "grams": float(r.grams or 0),
            "kcal": float(r.kcal or 0),
            "protein_g": float(r.protein_g or 0),
            "carbs_g": float(r.carbs_g or 0),
            "fat_g": float(r.fat_g or 0),
        }
        for r in rows
    ]
    return {"day": str(day), "items": items, "total": total}
