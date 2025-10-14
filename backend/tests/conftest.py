import os
import asyncio
import tempfile
from typing import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlmodel import Session, SQLModel, create_engine

from app.main import app as real_app
from app.db import get_session


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
def test_app(monkeypatch) -> Iterator[FastAPI]:
    # Use a fresh SQLite DB file in a temp dir per test for isolation
    tmp = tempfile.TemporaryDirectory()
    db_url = f"sqlite:///{os.path.join(tmp.name, 'test.db')}"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    # Initialize tables
    from app.models import foods, meals, wearables  # noqa: F401
    SQLModel.metadata.create_all(engine)

    def _override_get_session():
        with Session(engine) as session:
            yield session

    # clone app instance routing-wise by using real_app and overriding deps
    real_app.dependency_overrides[get_session] = _override_get_session

    try:
        yield real_app
    finally:
        real_app.dependency_overrides.clear()
        try:
            engine.dispose()
        except Exception:
            pass
        tmp.cleanup()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
