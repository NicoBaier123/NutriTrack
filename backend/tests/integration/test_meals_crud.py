import pytest

from app.models.foods import Food


@pytest.mark.asyncio
async def test_meal_item_patch_and_delete(client, db_session):
    food = Food(name="Banane", kcal=89, protein_g=1.1, carbs_g=22.8, fat_g=0.3)
    db_session.add(food)
    db_session.commit()

    create_resp = await client.post(
        "/meals/item",
        params={"day": "2025-01-02", "food_name": "Banane", "grams": 150},
    )
    assert create_resp.status_code == 201, create_resp.text
    item_id = create_resp.json()["item_id"]

    patch_resp = await client.patch(f"/meals/item/{item_id}", params={"grams": 200})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["grams"] == 200.0

    day_resp = await client.get("/meals/day", params={"day": "2025-01-02"})
    assert day_resp.status_code == 200
    payload = day_resp.json()
    assert len(payload["items"]) == 1
    totals = payload["totals"]
    expected_kcal = round(89 * 2.0, 1)
    assert totals["kcal"] == expected_kcal

    delete_resp = await client.delete(f"/meals/item/{item_id}")
    assert delete_resp.status_code == 204

    empty_resp = await client.get("/meals/day", params={"day": "2025-01-02"})
    assert empty_resp.status_code == 200
    assert empty_resp.json()["items"] == []


@pytest.mark.asyncio
async def test_meal_summary_by_food(client, db_session):
    banana = Food(name="Banane", kcal=89, protein_g=1.1, carbs_g=22.8, fat_g=0.3)
    oats = Food(name="Haferflocken", kcal=372, protein_g=13.5, carbs_g=58.7, fat_g=7.0)
    db_session.add_all([banana, oats])
    db_session.commit()

    await client.post(
        "/meals/item",
        params={"day": "2025-01-05", "food_name": "Banane", "grams": 120},
    )
    await client.post(
        "/meals/item",
        params={"day": "2025-01-05", "food_name": "Haferflocken", "grams": 80},
    )

    summary_resp = await client.get("/meals/summary_by_food", params={"day": "2025-01-05"})
    assert summary_resp.status_code == 200
    data = summary_resp.json()
    assert {item["food_name"] for item in data["items"]} == {"Banane", "Haferflocken"}
