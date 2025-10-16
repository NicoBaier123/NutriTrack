from datetime import date

import pytest
from fastapi import HTTPException

from app.models.foods import Food
from app.models.meals import Meal, MealItem
from app.routers import advisor


def _seed_foods(session):
    foods = [
        Food(name="Magerquark", kcal=67, protein_g=12.0, carbs_g=4.0, fat_g=0.2),
        Food(name="Haferflocken", kcal=372, protein_g=13.5, carbs_g=58.7, fat_g=7.0),
        Food(name="Banane", kcal=89, protein_g=1.1, carbs_g=22.8, fat_g=0.3),
    ]
    session.add_all(foods)
    session.commit()
    for food in foods:
        session.refresh(food)
    return foods


def _add_meal(session, meal_day: date, food: Food, grams: float = 200.0) -> Meal:
    meal = Meal(day=meal_day)
    session.add(meal)
    session.commit()
    session.refresh(meal)
    session.add(MealItem(meal_id=meal.id, food_id=food.id, grams=grams))
    session.commit()
    return meal


@pytest.mark.asyncio
async def test_advisor_gaps_calculates_remaining(client, db_session):
    foods = _seed_foods(db_session)
    target_day = date(2025, 1, 1)
    _add_meal(db_session, target_day, foods[0], grams=180)

    response = await client.get(
        "/advisor/gaps",
        params={"day": target_day.isoformat(), "body_weight_kg": 80},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["intake"]["kcal"] > 0
    assert payload["remaining"]["kcal"] > 0
    assert isinstance(payload["notes"], list)


@pytest.mark.asyncio
async def test_advisor_compose_fallback_without_llm(client, db_session, monkeypatch):
    _seed_foods(db_session)
    monkeypatch.setattr(advisor, "_ollama_alive", lambda timeout=2: False)
    monkeypatch.setattr(advisor, "LLAMA_CPP_AVAILABLE", False)
    monkeypatch.setattr(advisor, "LLAMA_CPP_MODEL_PATH", None)

    response = await client.post(
        "/advisor/compose",
        json={"message": "proteinreiches Abendessen", "servings": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["ideas"]) >= 1
    assert any("Fallback" in note for note in payload.get("notes", []))


@pytest.mark.asyncio
async def test_advisor_recommendations_fallback_without_llm(client, db_session, monkeypatch):
    foods = _seed_foods(db_session)
    target_day = date(2025, 1, 2)
    _add_meal(db_session, target_day, foods[1], grams=90)

    def _raise_http_exc(*_args, **_kwargs):
        raise HTTPException(status_code=503, detail="offline")

    monkeypatch.setattr(advisor, "_ollama_generate", _raise_http_exc)

    response = await client.get(
        "/advisor/recommendations",
        params={
            "day": target_day.isoformat(),
            "body_weight_kg": 80,
            "mode": "db",
            "max_suggestions": 3,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["suggestions"], payload
    assert all(s["source"] == "db" for s in payload["suggestions"])
