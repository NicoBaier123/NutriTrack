# backend/app/routers/wearables.py
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from ..db import get_session
from ..models.wearables import (
    WearableDaily,
    WearableDailyRead,
    WearableDailyUpsert,
)

router = APIRouter()


@router.get("/ping", summary="Wearables-Router erreichbar?")
def ping():
    return {"ok": True, "router": "wearables"}


@router.post(
    "/daily",
    response_model=WearableDailyRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create/Update tägliche Wearable-Metriken (Upsert: eindeutig durch day+source)",
)
def upsert_daily(
    payload: WearableDailyUpsert,
    session: Session = Depends(get_session),
):
    """
    Upsert anhand des Schlüssels (day, source):
    - Existiert Eintrag → partial update (nur gesetzte Felder).
    - Andernfalls → create.
    """
    try:
        # bestehenden Datensatz suchen
        stmt = select(WearableDaily).where(
            WearableDaily.day == payload.day,
            WearableDaily.source == payload.source,
        )
        row = session.exec(stmt).first()

        if row:
            # Nur Felder überschreiben, die im Payload gesetzt sind
            data = payload.dict(exclude_unset=True)
            # Schlüssel nicht änderbar
            data.pop("day", None)
            data.pop("source", None)

            for k, v in data.items():
                setattr(row, k, v)

            session.add(row)
            session.commit()
            session.refresh(row)
            return row

        # create
        new_row = WearableDaily(**payload.dict(exclude_unset=True))
        session.add(new_row)
        session.commit()
        session.refresh(new_row)
        return new_row

    except IntegrityError as e:
        session.rollback()
        # z. B. Unique-Constraint verletzt
        raise HTTPException(status_code=409, detail=f"Constraint error: {str(e.orig)}")
    except OperationalError as e:
        session.rollback()
        # z. B. "no such table: wearable_daily"
        raise HTTPException(status_code=500, detail=f"DB error: {str(e.orig)}")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Server error: {repr(e)}")


@router.get(
    "/daily",
    response_model=List[WearableDailyRead],
    summary="Liste täglicher Wearable-Metriken (Filter & Limit)",
)
def list_daily(
    source: Optional[str] = Query(default=None, description="Filter by data source (z. B. garmin, strava)"),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD inclusive"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD inclusive"),
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    try:
        stmt = select(WearableDaily).order_by(WearableDaily.day.desc()).limit(limit)

        if source:
            stmt = stmt.where(WearableDaily.source == source)
        if date_from:
            from datetime import date as _date
            stmt = stmt.where(WearableDaily.day >= _date.fromisoformat(date_from))
        if date_to:
            from datetime import date as _date
            stmt = stmt.where(WearableDaily.day <= _date.fromisoformat(date_to))

        rows = session.exec(stmt).all()
        return rows

    except OperationalError as e:
        # Typisches DB-Problem
        raise HTTPException(status_code=500, detail=f"DB error: {str(e.orig)}")
    except Exception as e:
        # Fallback für sonstige Fehler (Serialisierung/Validierung etc.)
        raise HTTPException(status_code=500, detail=f"Server error: {repr(e)}")
