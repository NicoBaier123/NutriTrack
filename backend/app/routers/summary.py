from fastapi import APIRouter, Depends
from datetime import date
from sqlmodel import Session, select, func
from ..db import get_session
from ..models.wearables import WearableDaily
from ..models.meals import Meal, MealItem
from ..models.foods import Food

router = APIRouter(prefix="/summary", tags=["summary"])

@router.get("/day")
def summary_day(
    day: date,
    body_weight_kg: float,
    source: str | None = None,
    session: Session = Depends(get_session),
):
    # Aktivität
    wq = select(WearableDaily).where(WearableDaily.day == day)
    if source:
        wq = wq.where(WearableDaily.source == source)
    wd = session.exec(wq).first()
    active_minutes = wd.active_minutes if wd and wd.active_minutes is not None else 0

    target_kcal = 28.0 * body_weight_kg + 5.0 * active_minutes

    # Intake
    iq = (
        select(func.coalesce(func.sum(Food.kcal * (MealItem.grams / 100.0)), 0.0))
        .select_from(Meal)
        .join(MealItem, MealItem.meal_id == Meal.id, isouter=True)
        .join(Food, Food.id == MealItem.food_id, isouter=True)
        .where(Meal.day == day)
    )
    intake_kcal = float(session.exec(iq).one())

    delta = intake_kcal - target_kcal
    notes = []
    if delta < -250:
        notes.append("Deutliche Unterdeckung – ggf. Energiezufuhr erhöhen.")
    elif delta > 250:
        notes.append("Deutliche Überdeckung – ggf. Intake drosseln.")
    else:
        notes.append("In der Nähe des Ziels.")

    return {
        "day": str(day),
        "active_minutes": active_minutes,
        "target_kcal": round(target_kcal, 1),
        "intake_kcal": round(intake_kcal, 1),
        "delta_kcal": round(delta, 1),
        "notes": notes,
    }
