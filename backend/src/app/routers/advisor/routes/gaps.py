from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from app.core.database import get_session
from app.routers.summary import (
    _active_minutes_for_day,
    _intake_for_day,
    _target_kcal_for_day,
)

from ..helpers import _mk_goal_kcal
from ..schemas import GapsResponse, MacroTotals

router = APIRouter()


@router.get("/gaps", response_model=GapsResponse)
def gaps(
    day: date = Query(...),
    body_weight_kg: Optional[float] = Query(None, ge=0.0),
    goal: str = Query("maintain"),
    protein_g_per_kg: float = Query(1.8, ge=1.2, le=2.4),
    goal_mode: str = Query("percent"),
    goal_percent: float = Query(
        10.0, ge=0.0, le=25.0, description="+/-% vom TDEE bei bulk/cut"
    ),
    goal_kcal_offset: float = Query(300.0, ge=0.0, le=1000.0),
    goal_rate_kg_per_week: float = Query(0.5, ge=0.1, le=1.0),
    session: Session = Depends(get_session),
):
    intake_totals = _intake_for_day(session, day)
    intake = MacroTotals(
        kcal=float(round(intake_totals.kcal, 1)),
        protein_g=float(round(intake_totals.protein_g, 1)),
        carbs_g=float(round(intake_totals.carbs_g, 1)),
        fat_g=float(round(intake_totals.fat_g, 1)),
        fiber_g=float(round(getattr(intake_totals, "fiber_g", 0.0), 1)),
    )
    target = None
    notes = []

    if body_weight_kg is not None:
        active_min = _active_minutes_for_day(session, day)
        base_kcal = _target_kcal_for_day(body_weight_kg, active_min) or 0.0

        adj_kcal = _mk_goal_kcal(
            base_kcal=base_kcal,
            goal=goal,
            goal_mode=goal_mode,
            percent=goal_percent,
            offset_kcal=goal_kcal_offset,
            rate_kg_per_week=goal_rate_kg_per_week,
        )

        target_protein = protein_g_per_kg * body_weight_kg
        target = MacroTotals(
            kcal=round(max(adj_kcal, 0.0), 0),
            protein_g=round(max(target_protein, 0.0), 0),
            carbs_g=0.0,
            fat_g=0.0,
            fiber_g=0.0,
        )
        notes.append(
            f"Ziel kcal via TDEE {round(base_kcal)} & Goal={goal} ({goal_mode}). Protein {protein_g_per_kg} g/kg."
        )

    remaining = None
    if target:
        remaining = MacroTotals(
            kcal=round(target.kcal - intake.kcal, 1),
            protein_g=round(target.protein_g - intake.protein_g, 1),
            carbs_g=round(target.carbs_g - intake.carbs_g, 1),
            fat_g=round(target.fat_g - intake.fat_g, 1),
            fiber_g=round(target.fiber_g - intake.fiber_g, 1),
        )
        if remaining.kcal <= 0:
            notes.append("Kalorienziel erreicht/überschritten.")
        if remaining.protein_g > 0:
            notes.append("Protein unter Ziel – priorisiere proteinreiche Auswahl.")

    return GapsResponse(day=day, target=target, intake=intake, remaining=remaining, notes=notes)

