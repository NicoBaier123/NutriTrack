import pytest


@pytest.mark.asyncio
async def test_wearables_upsert_and_list(client):
    base_payload = {
        "day": "2025-01-01",
        "source": "garmin",
        "steps": 12000,
        "calories": 700.5,
        "active_minutes": 90,
    }

    create_resp = await client.post("/wearables/daily", json=base_payload)
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["steps"] == 12000
    assert created["calories"] == 700.5

    update_resp = await client.post(
        "/wearables/daily",
        json={
            "day": "2025-01-01",
            "source": "garmin",
            "steps": 13500,
        },
    )
    assert update_resp.status_code == 201, update_resp.text
    updated = update_resp.json()
    assert updated["steps"] == 13500
    # calories should remain unchanged because field was omitted in the update payload
    assert updated["calories"] == 700.5

    list_resp = await client.get("/wearables/daily", params={"source": "garmin", "limit": 10})
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["steps"] == 13500
    assert items[0]["calories"] == 700.5
