# backend/app/routers/meals.py
from __future__ import annotations

import os
from datetime import date
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func

from ..db import get_session
from ..utils.nutrition import macros_for_grams, round_macros
from ..models.meals import Meal, MealItem, MealType
from ..models.foods import Food

router = APIRouter(prefix="/meals", tags=["meals"])

# Optionales Verhalten für die Demo (per Umgebungsvariablen steuerbar)
FUZZY_FOOD = os.getenv("FUZZY_FOOD", "0") in ("1", "true", "True")
AUTOCREATE_FOOD = os.getenv("AUTOCREATE_FOOD", "0") in ("1", "true", "True")


def _find_food(session: Session, food_name: str) -> Optional[Food]:
    """Exakter Treffer, optional fuzzy (ILIKE %name%)."""
    food = session.exec(select(Food).where(Food.name == food_name)).first()
    if food or not FUZZY_FOOD:
        return food
    # Fuzzy-Fallback
    q = food_name.strip()
    return session.exec(select(Food).where(Food.name.ilike(f"%{q}%"))).first()


@router.post("/item", status_code=201)
def add_meal_item(
    day: date,
    food_name: str,
    grams: float = Query(..., gt=0),
    type: Optional[MealType] = None,
    session: Session = Depends(get_session),
):
    """Ein einzelnes MealItem an einem Tag anlegen (Meal wird bei Bedarf erstellt)."""
    food = _find_food(session, food_name)

    if not food:
        if AUTOCREATE_FOOD:
            # Demo-Notlösung: Food ohne Makros anlegen, damit UI-Flow nicht bricht
            food = Food(name=food_name, kcal=0.0, protein_g=0.0, carbs_g=0.0, fat_g=0.0)
            session.add(food)
            session.flush()
        else:
            raise HTTPException(404, f"Food '{food_name}' not found")

    # Meal holen/erstellen (pro Tag und optionalem MealType)
    meal_stmt = select(Meal).where(Meal.day == day)
    meal_stmt = meal_stmt.where(Meal.type == type) if type is not None else meal_stmt.where(Meal.type.is_(None))
    meal = session.exec(meal_stmt).first()
    if not meal:
        meal = Meal(day=day, type=type)
        session.add(meal)
        session.flush()

    item = MealItem(meal_id=meal.id, food_id=food.id, grams=grams)
    session.add(item)
    session.commit()
    session.refresh(item)
    return {
        "meal_id": meal.id,
        "item_id": item.id,
        "food": food.name,
        "grams": grams,
        "type": meal.type,
    }


@router.get("/day")
def get_day(
    day: date = Query(...),
    session: Session = Depends(get_session),
):
    """
    Liefert ALLE MealItems des Tages (nicht aggregiert) inkl. Food-Namen
    und geschätzten Makros pro Item. Zusätzlich Gesamtsummen (totals).

    Passt zu der Demo-UI, die `food_name`, `grams` und Makros erwartet.
    """
    # Spalten robust holen (falls Spaltennamen variieren sollten)
    kcal_col = getattr(Food, "kcal", None) or getattr(Food, "kcal_100g")
    protein_col = getattr(Food, "protein_g", None) or getattr(Food, "protein")
    carbs_col = getattr(Food, "carbs_g", None) or getattr(Food, "carbs")
    fat_col = getattr(Food, "fat_g", None) or getattr(Food, "fat")

    rows = session.exec(
        select(
            MealItem.id,           # 0
            MealItem.grams,        # 1
            Meal.id,               # 2
            Meal.type,             # 3
            Food.id,               # 4
            Food.name,             # 5
            kcal_col,              # 6
            protein_col,           # 7
            carbs_col,             # 8
            fat_col,               # 9
        )
        .join(Meal, Meal.id == MealItem.meal_id)
        .join(Food, Food.id == MealItem.food_id)
        .where(Meal.day == day)
        .order_by(MealItem.id.asc())
    ).all()

    items: List[Dict[str, Any]] = []
    totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}

    for (item_id, grams, meal_id, meal_type, food_id, food_name,
         kcal100, p100, c100, f100) in rows:
        m = macros_for_grams(kcal100, p100, c100, f100, grams or 0.0)
        rm = round_macros(m, 1)
        kcal, prot, carbs, fat = rm.kcal, rm.protein_g, rm.carbs_g, rm.fat_g

        items.append({
            "item_id": int(item_id),
            "meal_id": int(meal_id),
            "type": meal_type.value if isinstance(meal_type, MealType) else meal_type,
            "food_id": int(food_id),
            "food_name": food_name,
            "grams": float(grams or 0.0),
            "kcal": kcal,
            "protein_g": prot,
            "carbs_g": carbs,
            "fat_g": fat,
        })
        totals["kcal"] += m.kcal
        totals["protein_g"] += m.protein_g
        totals["carbs_g"] += m.carbs_g
        totals["fat_g"] += m.fat_g

    for k in totals:
        totals[k] = round(totals[k], 1)

    return {"day": day.isoformat(), "items": items, "totals": totals}


@router.get("/summary_by_food", summary="(Optional) Aggregierte Tageswerte je Food")
def summary_by_food(
    day: date = Query(...),
    session: Session = Depends(get_session),
):
    """
    Aggregiert den Tag je Food (Summe Gramm & Makros).
    Praktisch für Tabellen/Reports; von der Demo-UI nicht benötigt.
    """
    kcal_col = getattr(Food, "kcal", None) or getattr(Food, "kcal_100g")
    protein_col = getattr(Food, "protein_g", None) or getattr(Food, "protein")
    carbs_col = getattr(Food, "carbs_g", None) or getattr(Food, "carbs")
    fat_col = getattr(Food, "fat_g", None) or getattr(Food, "fat")

    q = (
        select(
            Food.id.label("food_id"),
            Food.name.label("food_name"),
            func.sum(MealItem.grams).label("grams"),
            (func.sum(MealItem.grams) * kcal_col / 100.0).label("kcal"),
            (func.sum(MealItem.grams) * protein_col / 100.0).label("protein_g"),
            (func.sum(MealItem.grams) * carbs_col / 100.0).label("carbs_g"),
            (func.sum(MealItem.grams) * fat_col / 100.0).label("fat_g"),
        )
        .join(Meal, Meal.id == MealItem.meal_id)
        .join(Food, Food.id == MealItem.food_id)
        .where(Meal.day == day)
        .group_by(Food.id, Food.name)
        .order_by(Food.name.asc())
    )
    rows = session.exec(q).all()

    items = [{
        "food_id": int(r.food_id),
        "food_name": r.food_name,
        "grams": float(r.grams or 0.0),
        "kcal": round(float(r.kcal or 0.0), 1),
        "protein_g": round(float(r.protein_g or 0.0), 1),
        "carbs_g": round(float(r.carbs_g or 0.0), 1),
        "fat_g": round(float(r.fat_g or 0.0), 1),
    } for r in rows]

    totals = {
        "kcal": round(sum(i["kcal"] for i in items), 1),
        "protein_g": round(sum(i["protein_g"] for i in items), 1),
        "carbs_g": round(sum(i["carbs_g"] for i in items), 1),
        "fat_g": round(sum(i["fat_g"] for i in items), 1),
    }

    return {"day": day.isoformat(), "items": items, "totals": totals}


@router.get("/items", summary="Roh-Items des Tages (inkl. Meal-Type) listen")
def list_items(day: date, session: Session = Depends(get_session)):
    q = (
        select(MealItem.id, Meal.type, Food.name, MealItem.grams)
        .join(Meal, Meal.id == MealItem.meal_id)
        .join(Food, Food.id == MealItem.food_id)
        .where(Meal.day == day)
        .order_by(Meal.id.asc(), MealItem.id.asc())
    )
    rows = session.exec(q).all()
    return [
        {
            "id": int(r.id),
            "type": (r.type.value if isinstance(r.type, MealType) else r.type),
            "food": r.name,
            "grams": float(r.grams),
        }
        for r in rows
    ]


@router.delete("/item/{item_id}", status_code=204)
def delete_item(item_id: int, session: Session = Depends(get_session)):
    item = session.get(MealItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    session.delete(item)
    session.commit()
    return


@router.patch("/item/{item_id}", summary="Grammzahl eines Items ändern")
def patch_item(item_id: int, grams: float = Query(..., gt=0), session: Session = Depends(get_session)):
    item = session.get(MealItem, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    item.grams = grams
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"item_id": item.id, "grams": item.grams}
