from datetime import date

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.models.foods import Food
from app.models.meals import Meal, MealItem
from app.models.recipes import Recipe, RecipeItem
from app.routers import advisor
from app.utils import llm as llm_utils


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
    monkeypatch.setattr(advisor.SETTINGS, "advisor_llm_enabled", False)
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
    notes_text = " ".join(payload.get("notes", []))
    assert "fallback" in notes_text.lower() or "llm deaktiviert" in notes_text.lower()

    recipes = db_session.exec(select(Recipe)).all()
    assert len(recipes) == len(payload["ideas"])
    assert all(r.source == "fallback" for r in recipes)
    ingredients = db_session.exec(select(RecipeItem)).all()
    assert ingredients


@pytest.mark.asyncio
async def test_advisor_compose_persists_llm_recipes(client, db_session, monkeypatch):
    monkeypatch.setattr(advisor.SETTINGS, "advisor_llm_enabled", True)
    _seed_foods(db_session)
    monkeypatch.setattr(advisor, "_ollama_alive", lambda timeout=2: True)
    monkeypatch.setattr(advisor, "LLAMA_CPP_AVAILABLE", False)
    monkeypatch.setattr(advisor, "LLAMA_CPP_MODEL_PATH", None)

    def fake_llm_generate_json(*_args, **_kwargs):
        return [
            {
                "title": "Protein Bowl",
                "time_minutes": 15,
                "difficulty": "easy",
                "ingredients": [
                    {"name": "Magerquark", "grams": 200},
                    {"name": "Banane", "grams": 100},
                ],
                "instructions": ["Mix everything", "Serve cold"],
                "macros": {"kcal": 520, "protein_g": 48, "carbs_g": 45, "fat_g": 12},
                "tags": ["test", "llm"],
            }
        ]

    monkeypatch.setattr(llm_utils, "llm_generate_json", fake_llm_generate_json)

    response = await client.post(
        "/advisor/compose",
        json={"message": "Test LLM recipe", "servings": 2},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["ideas"], payload

    recipes = db_session.exec(select(Recipe)).all()
    assert recipes and recipes[0].source == "llm"
    ingredients = db_session.exec(select(RecipeItem).where(RecipeItem.recipe_id == recipes[0].id)).all()
    assert ingredients


@pytest.mark.asyncio
async def test_advisor_recommendations_fallback_without_llm(client, db_session, monkeypatch):
    monkeypatch.setattr(advisor.SETTINGS, "advisor_llm_enabled", False)
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
