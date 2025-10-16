# backend/app/routers/meals_ingest.py
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from sqlmodel import Session, select

from app.db import get_session
from app.models.foods import Food
from app.models.foods_extra import FoodSynonym, FoodPending
from app.models.meals import Meal, MealItem

router = APIRouter(prefix="/meals", tags=["meals"])

# ---------- Schemas ----------
class IngestItem(BaseModel):
    food_name: str = Field(min_length=1)
    grams: float = Field(gt=0)

class IngestRequest(BaseModel):
    day: date
    items: List[IngestItem]
    source: Literal["chat","manual","import"] = "chat"
    input_text: Optional[str] = None  # Rohtext zur Nachvollziehbarkeit

class IngestResultItem(BaseModel):
    food_name: str
    grams: float
    food_id: Optional[int] = None
    status: Literal["added","not_found","skipped"]
    reason: Optional[str] = None

class IngestResponse(BaseModel):
    meal_id: Optional[int]
    added: int
    not_found: int
    skipped: int
    items: List[IngestResultItem]

# ---------- Helpers ----------
def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(s.split())

def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii","ignore").decode().lower()
    s = re.sub(r"\(.*?\)", " ", s)                      # Klammern raus
    s = re.sub(r"\b\d+([.,]\d+)?\s*(g|ml|kg|l)\b", " ", s)  # Einheiten raus
    s = re.sub(r"[\W_]+", " ", s)
    return " ".join(s.split())

def _resolve_food(session: Session, name: str) -> Optional[Food]:
    raw = (name or "").strip()
    if not raw: return None
    n = _normalize(raw)

    # 1) exakter Name
    f = session.exec(select(Food).where(Food.name.ilike(raw))).first()
    if f: return f

    # 2) Synonyme (auf normalisiertem Schlüssel)
    syn = session.exec(select(FoodSynonym).where(FoodSynonym.synonym.ilike(n))).first()
    if syn:
        return session.exec(select(Food).where(Food.id == syn.food_id)).first()

    # 3) Fuzzy auf Food-Namen + Synonyme
    foods = session.exec(select(Food)).all()
    names = [getattr(x, "name", "") for x in foods]
    syns  = session.exec(select(FoodSynonym)).all()
    pool  = names + [s.synonym for s in syns]

    best = process.extractOne(n, pool, scorer=fuzz.WRatio) if pool else None
    if best:
        cand, score, _ = best
        if score >= 95:
            tgt = session.exec(select(Food).where(Food.name.ilike(cand))).first()
            if tgt: return tgt
            syn2 = session.exec(select(FoodSynonym).where(FoodSynonym.synonym.ilike(cand))).first()
            if syn2:
                return session.exec(select(Food).where(Food.id == syn2.food_id)).first()
        elif score >= 90:
            try:
                session.add(FoodPending(original_name=raw, cleaned_name=n, top_suggestion=cand, top_score=score))
                session.flush()
            except Exception:
                pass
            return None

    # 4) Kein Treffer
    try:
        session.add(FoodPending(original_name=raw, cleaned_name=n))
        session.flush()
    except Exception:
        pass
    return None

def _ingest_hash(req: IngestRequest) -> str:
    payload = f"{req.day}|{req.source}|{[(i.food_name,i.grams) for i in req.items]}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()

# ---------- Route ----------
@router.post("/ingest", response_model=IngestResponse, summary="Alle Zutaten eines Inputs atomar speichern")
def ingest_meal(req: IngestRequest, session: Session = Depends(get_session)):
    if not req.items:
        raise HTTPException(status_code=400, detail="items must not be empty")

    results: list[IngestResultItem] = []
    added = skipped = not_found = 0

    # Alles-oder-nichts
    with session.begin():
        ihash = _ingest_hash(req)

        # Idempotenz: gleiche Payload nicht doppelt speichern
        existing = session.exec(select(Meal).where(Meal.import_hash == ihash)).first()
        if existing:
            raise HTTPException(status_code=409, detail="Duplicate ingestion (same items & day)")

        meal = Meal(day=req.day, source=req.source, input_text=req.input_text, import_hash=ihash, created_at=datetime.utcnow())
        session.add(meal)
        session.flush()  # meal.id

        for it in req.items:
            food = _resolve_food(session, it.food_name)
            if not food:
                not_found += 1
                results.append(IngestResultItem(
                    food_name=it.food_name, grams=it.grams,
                    status="not_found", reason="Kein Food-Match in DB"
                ))
                continue

            # Duplikate im selben Meal aggregieren
            existing_item = session.exec(
                select(MealItem).where(MealItem.meal_id == meal.id, MealItem.food_id == food.id)
            ).first()
            if existing_item:
                existing_item.grams += it.grams
                skipped += 1
                results.append(IngestResultItem(
                    food_name=it.food_name, grams=it.grams,
                    food_id=food.id, status="skipped", reason="aggregated with existing item"
                ))
            else:
                session.add(MealItem(meal_id=meal.id, food_id=food.id, grams=it.grams))
                added += 1
                results.append(IngestResultItem(
                    food_name=it.food_name, grams=it.grams, food_id=food.id, status="added"
                ))

        # Wenn nichts gematcht wurde → rollback (durch Exception)
        if added == 0:
            raise HTTPException(status_code=422, detail="No items matched Food DB")

    return IngestResponse(
        meal_id=meal.id, added=added, skipped=skipped, not_found=not_found, items=results
    )
