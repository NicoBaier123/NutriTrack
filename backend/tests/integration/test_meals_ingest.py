import pytest

from app.models.foods import Food


@pytest.mark.asyncio
async def test_meal_ingest_handles_duplicates(client, db_session):
    apple = Food(name="Apple", kcal=52, protein_g=0.3, carbs_g=14.0, fat_g=0.2)
    db_session.add(apple)
    db_session.commit()

    resp = await client.post(
        "/meals/ingest",
        json={
            "day": "2025-01-03",
            "source": "chat",
            "input_text": "apple twice",
            "items": [
                {"food_name": "Apple", "grams": 150},
                {"food_name": "Apple", "grams": 50},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["added"] == 1
    assert payload["skipped"] == 1
    assert payload["not_found"] == 0
    statuses = {item["status"] for item in payload["items"]}
    assert statuses == {"added", "skipped"}
