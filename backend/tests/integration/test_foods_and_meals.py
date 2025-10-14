import pytest
from sqlmodel import Session

from app.models.foods import Food


@pytest.mark.asyncio
async def test_food_search_and_detail(client, test_app):
    # seed
    from app.db import get_session

    for override in test_app.dependency_overrides.values():
        pass

    sess_gen = test_app.dependency_overrides[get_session]()
    session: Session = next(sess_gen)
    try:
        session.add_all([
            Food(name="Magerquark", kcal=67, protein_g=12, carbs_g=4, fat_g=0.2),
            Food(name="Haferflocken", kcal=372, protein_g=13.5, carbs_g=58.7, fat_g=7),
        ])
        session.commit()
    finally:
        try:
            next(sess_gen)
        except StopIteration:
            pass

    r = await client.get("/foods/search", params={"q": "mag"})
    assert r.status_code == 200
    names = r.json()
    assert any("Magerquark" == n for n in names)

    r = await client.get("/foods/detail", params={"name": "Haferflocken"})
    assert r.status_code == 200
    d = r.json()
    assert d["kcal"] == 372
    assert d["protein_g"] == 13.5


@pytest.mark.asyncio
async def test_meals_day_totals(client, test_app):
    # seed foods
    from app.db import get_session
    sess_gen = test_app.dependency_overrides[get_session]()
    session: Session = next(sess_gen)
    try:
        mq = Food(name="Magerquark", kcal=67, protein_g=12, carbs_g=4, fat_g=0.2)
        oats = Food(name="Haferflocken", kcal=372, protein_g=13.5, carbs_g=58.7, fat_g=7)
        session.add_all([mq, oats])
        session.commit()
    finally:
        try:
            next(sess_gen)
        except StopIteration:
            pass

    # add items
    r = await client.post("/meals/item", params={"day": "2025-01-01", "food_name": "Magerquark", "grams": 250})
    assert r.status_code == 201, r.text
    r = await client.post("/meals/item", params={"day": "2025-01-01", "food_name": "Haferflocken", "grams": 80})
    assert r.status_code == 201, r.text

    # fetch day
    r = await client.get("/meals/day", params={"day": "2025-01-01"})
    assert r.status_code == 200
    data = r.json()
    totals = data["totals"]
    # expected
    exp_kcal = round(67*2.5 + 372*0.8, 1)
    exp_prot = round(12*2.5 + 13.5*0.8, 1)
    exp_carbs = round(4*2.5 + 58.7*0.8, 1)
    exp_fat = round(0.2*2.5 + 7*0.8, 1)
    assert totals == {
        "kcal": exp_kcal,
        "protein_g": exp_prot,
        "carbs_g": exp_carbs,
        "fat_g": exp_fat,
    }
