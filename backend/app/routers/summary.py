# backend/app/routers/summary.py

from datetime import date, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func

from app.db import get_session
from app.models.wearables import WearableDaily
from app.models.foods import Food
from app.models.meals import Meal, MealItem

router = APIRouter(prefix="/summary", tags=["summary"])

# ----------------------------
# Pydantic Schemas
# ----------------------------

class IntakeTotals(BaseModel):
    kcal: float = 0.0
    protein_g: float = 0.0
    carbs_g: float = 0.0
    fat_g: float = 0.0

class DayDetail(BaseModel):
    day: date
    target_kcal: Optional[float] = None
    intake: IntakeTotals
    delta_kcal: Optional[float] = None

class WeekAverages(BaseModel):
    target_kcal: Optional[float] = None
    intake_kcal: float
    delta_kcal: Optional[float] = None

class TrendInfo(BaseModel):
    intake_direction: str  # "up" | "down" | "flat"
    intake_change_abs: float
    method: str = "last3_vs_first3_avg"

class WeekSummaryResponse(BaseModel):
    start_day: date
    end_day: date
    days: int
    totals: IntakeTotals
    averages: WeekAverages
    trend: TrendInfo
    days_detail: List[DayDetail]
    notes: List[str] = []


# ----------------------------
# Helper: Meals → Tagesintake
# ----------------------------

def _intake_for_day(session: Session, d: date) -> IntakeTotals:
    """
    Aggregiert kcal/protein/carbs/fat über alle MealItems eines Tages.
    Explizit auf MealItem geankert, um doppelte FROM-Einträge zu vermeiden.
    Robust gegenüber Spaltennamen: protein|protein_g, carbs|carbs_g, fat|fat_g.
    """
    kcal_col    = getattr(Food, "kcal", None) or getattr(Food, "kcal_100g")
    protein_col = getattr(Food, "protein_g", None) or getattr(Food, "protein")
    carbs_col   = getattr(Food, "carbs_g", None) or getattr(Food, "carbs")
    fat_col     = getattr(Food, "fat_g", None) or getattr(Food, "fat")

    if kcal_col is None or protein_col is None or carbs_col is None or fat_col is None:
        raise RuntimeError("Food-Spalten nicht gefunden (kcal/protein[_g]/carbs[_g]/fat[_g]).")

    stmt = (
        select(
            func.coalesce(func.sum(kcal_col    * (MealItem.grams / 100.0)), 0.0),
            func.coalesce(func.sum(protein_col * (MealItem.grams / 100.0)), 0.0),
            func.coalesce(func.sum(carbs_col   * (MealItem.grams / 100.0)), 0.0),
            func.coalesce(func.sum(fat_col     * (MealItem.grams / 100.0)), 0.0),
        )
        .select_from(MealItem)  # <<< WICHTIG: eindeutiger Anker
        .join(Meal, Meal.id == MealItem.meal_id)
        .join(Food, Food.id == MealItem.food_id)
        .where(Meal.day == d)
    )

    kcal, protein_g, carbs_g, fat_g = session.exec(stmt).one()
    return IntakeTotals(
        kcal=float(kcal or 0.0),
        protein_g=float(protein_g or 0.0),
        carbs_g=float(carbs_g or 0.0),
        fat_g=float(fat_g or 0.0),
    )


# ----------------------------
# Helper: Wearables → aktive Minuten
# ----------------------------

def _active_minutes_for_day(session: Session, d: date) -> int:
    active_col = getattr(WearableDaily, "active_minutes", None) or getattr(WearableDaily, "active_minutes_total", None)
    stmt = select(func.max(active_col)).where(WearableDaily.day == d)
    value = session.exec(stmt).one()
    return int(value or 0)



def _target_kcal_for_day(body_weight_kg: Optional[float], active_minutes: int) -> Optional[float]:
    if body_weight_kg is None:
        return None
    return 28.0 * float(body_weight_kg) + 5.0 * float(active_minutes)


# ----------------------------
# Helper: Trend (einfach & robust)
# ----------------------------

def _trend_last3_vs_first3(intake_per_day: List[DayDetail]) -> TrendInfo:
    """
    Vergleicht ØIntake der letzten 3 Tage vs. ersten 3 Tage des Fensters.
    Bei <6 Tagen wird so gut wie möglich gemittelt (z.B. 2 vs 2).
    """
    n = len(intake_per_day)
    if n == 0:
        return TrendInfo(intake_direction="flat", intake_change_abs=0.0)

    k = min(3, n // 2) or 1
    first_avg = sum(dd.intake.kcal for dd in intake_per_day[:k]) / k
    last_avg  = sum(dd.intake.kcal for dd in intake_per_day[-k:]) / k
    diff = last_avg - first_avg

    direction = "flat"
    eps = 100.0  # Schwelle in kcal für "sichtbar"
    if diff > eps:
        direction = "up"
    elif diff < -eps:
        direction = "down"

    return TrendInfo(intake_direction=direction, intake_change_abs=round(diff, 1))


# ----------------------------
# Endpoint: /summary/week
# ----------------------------

@router.get("/week", response_model=WeekSummaryResponse)
def get_summary_week(
    end_day: Optional[date] = Query(default=None),
    days: int = Query(default=7, ge=1, le=31),
    body_weight_kg: Optional[float] = Query(default=None, ge=0.0),
    session: Session = Depends(get_session),
):
    end_d = end_day or date.today()
    start_d = end_d - timedelta(days=days - 1)

    # Detail-Liste aufbauen (aufsteigend nach Tag)
    day_cursor = start_d
    details: List[DayDetail] = []

    total_intake = IntakeTotals()

    while day_cursor <= end_d:
        intake = _intake_for_day(session, day_cursor)
        active_min = _active_minutes_for_day(session, day_cursor)
        tgt = _target_kcal_for_day(body_weight_kg, active_min)

        delta = None
        if tgt is not None:
            delta = float(round(intake.kcal - tgt, 1))

        # Totals aufsummieren
        total_intake.kcal += intake.kcal
        total_intake.protein_g += intake.protein_g
        total_intake.carbs_g += intake.carbs_g
        total_intake.fat_g += intake.fat_g

        details.append(
            DayDetail(
                day=day_cursor,
                target_kcal=None if tgt is None else float(round(tgt, 1)),
                intake=IntakeTotals(
                    kcal=float(round(intake.kcal, 1)),
                    protein_g=float(round(intake.protein_g, 1)),
                    carbs_g=float(round(intake.carbs_g, 1)),
                    fat_g=float(round(intake.fat_g, 1)),
                ),
                delta_kcal=None if delta is None else float(round(delta, 1)),
            )
        )
        day_cursor += timedelta(days=1)

    # Averages
    avg_target = None
    if body_weight_kg is not None:
        # Rechne targets erneut auf Basis der je-Tag aktiven Minuten, um den Mittelwert zu bilden
        tgt_values = [dd.target_kcal for dd in details if dd.target_kcal is not None]
        avg_target = float(round(sum(tgt_values) / len(tgt_values), 1)) if tgt_values else None

    avg_intake = float(round(total_intake.kcal / days, 1))
    avg_delta = None
    if avg_target is not None:
        avg_delta = float(round(avg_intake - avg_target, 1))

    # Trend
    trend = _trend_last3_vs_first3(details)

    # Notes (einfacher Heuristik-Block)
    notes: List[str] = []
    if avg_delta is not None:
        if avg_delta < -300:
            notes.append("Ø-Unterdeckung ≥ 300 kcal/Tag — Energiezufuhr erhöhen?")
        elif avg_delta > 300:
            notes.append("Ø-Überdeckung ≥ 300 kcal/Tag — ggf. drosseln?")
    # Anteil Unterdeckungstage (falls target vorhanden)
    if body_weight_kg is not None:
        under = sum(1 for dd in details if dd.delta_kcal is not None and dd.delta_kcal < 0)
        notes.append(f"Unterdeckung an {under}/{days} Tagen.")

    # Runden der Totals
    totals_rounded = IntakeTotals(
        kcal=float(round(total_intake.kcal, 1)),
        protein_g=float(round(total_intake.protein_g, 1)),
        carbs_g=float(round(total_intake.carbs_g, 1)),
        fat_g=float(round(total_intake.fat_g, 1)),
    )

    return WeekSummaryResponse(
        start_day=start_d,
        end_day=end_d,
        days=days,
        totals=totals_rounded,
        averages=WeekAverages(
            target_kcal=avg_target,
            intake_kcal=avg_intake,
            delta_kcal=avg_delta,
        ),
        trend=trend,
        days_detail=details,
        notes=notes,
    )



class DaySummaryResponse(BaseModel):
    day: date
    target_kcal: Optional[float] = None
    intake: IntakeTotals
    delta_kcal: Optional[float] = None
    notes: List[str] = []

@router.get("/day", response_model=DaySummaryResponse)
def get_summary_day(
    day: date = Query(...),
    body_weight_kg: Optional[float] = Query(default=None, ge=0.0),
    session: Session = Depends(get_session),
):
    intake = _intake_for_day(session, day)
    notes: List[str] = []
    target = None
    delta = None

    if body_weight_kg is not None:
        active_min = _active_minutes_for_day(session, day)
        target = _target_kcal_for_day(body_weight_kg, active_min)
        if target is not None:
            target = float(round(target, 1))
            delta = float(round(intake.kcal - target, 1))
        notes.append(f"Aktive Minuten: {active_min}")

    return DaySummaryResponse(
        day=day,
        target_kcal=target,
        intake=IntakeTotals(
            kcal=float(round(intake.kcal, 1)),
            protein_g=float(round(intake.protein_g, 1)),
            carbs_g=float(round(intake.carbs_g, 1)),
            fat_g=float(round(intake.fat_g, 1)),
        ),
        delta_kcal=delta,
        notes=notes,
    )
