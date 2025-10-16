from datetime import date

import pytest

from app.models.foods import Food
from app.models.meals import Meal, MealItem
from app.models.wearables import WearableDaily


def _add_meal(session, day: date, food_quantities):
    meal = Meal(day=day)
    session.add(meal)
    session.flush()
    for food, grams in food_quantities:
        session.add(MealItem(meal_id=meal.id, food_id=food.id, grams=grams))
    session.commit()


@pytest.mark.asyncio
async def test_summary_day_and_week(client, db_session):
    chicken = Food(name="Chicken Breast", kcal=165, protein_g=31, carbs_g=0.0, fat_g=3.6)
    rice = Food(name="Rice", kcal=130, protein_g=2.4, carbs_g=28.0, fat_g=0.3)
    db_session.add_all([chicken, rice])
    db_session.commit()

    day1 = date(2025, 1, 1)
    day2 = date(2025, 1, 2)

    _add_meal(db_session, day1, [(chicken, 200), (rice, 150)])
    _add_meal(db_session, day2, [(chicken, 100), (rice, 200)])

    db_session.add_all(
        [
            WearableDaily(day=day1, source="garmin", active_minutes=60),
            WearableDaily(day=day2, source="garmin", active_minutes=30),
        ]
    )
    db_session.commit()

    day_resp = await client.get(
        "/summary/day", params={"day": day1.isoformat(), "body_weight_kg": 80}
    )
    assert day_resp.status_code == 200
    day_payload = day_resp.json()
    assert day_payload["delta_kcal"] < 0  # under target because intake < target
    assert "Aktive Minuten" in day_payload["notes"][0]

    week_resp = await client.get(
        "/summary/week",
        params={
            "end_day": day2.isoformat(),
            "days": 2,
            "body_weight_kg": 80,
        },
    )
    assert week_resp.status_code == 200
    week_payload = week_resp.json()
    assert week_payload["days"] == 2
    assert week_payload["totals"]["kcal"] == 950.0
    assert week_payload["averages"]["intake_kcal"] == 475.0
    assert week_payload["trend"]["intake_change_abs"] == -100.0
