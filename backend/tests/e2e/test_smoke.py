import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    r = await client.get("/health")
    assert r.status_code in (200, 204)


@pytest.mark.asyncio
async def test_demo_page_served(client: AsyncClient):
    resp = await client.get("/demo")
    assert resp.status_code == 200
    assert "<title>NutriTrack Demo</title>" in resp.text
