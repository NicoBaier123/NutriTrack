import tempfile
from contextlib import suppress
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlmodel import Session, SQLModel, create_engine

from app import db as public_db
from app.core import database as core_database
from app.db import get_session
from app.main import create_app


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
def test_app(monkeypatch) -> Iterator[FastAPI]:
    # Use a fresh SQLite DB file in a temp dir per test for isolation
    tmp = tempfile.TemporaryDirectory()
    db_path = Path(tmp.name) / "test.db"
    db_url = f"sqlite:///{db_path}"

    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    # Initialize tables
    from app.models import foods, meals, wearables  # noqa: F401
    SQLModel.metadata.create_all(engine)

    def _override_get_session():
        with Session(engine) as session:
            yield session

    # patch global engine/init_db so startup hooks operate on the test database
    monkeypatch.setattr(core_database, "engine", engine, raising=False)
    monkeypatch.setattr(public_db, "engine", engine, raising=False)

    def _init_db():
        SQLModel.metadata.create_all(engine)

    monkeypatch.setattr(core_database, "init_db", _init_db, raising=False)
    monkeypatch.setattr(public_db, "init_db", _init_db, raising=False)

    app = create_app()
    app.dependency_overrides[get_session] = _override_get_session

    try:
        yield app
    finally:
        app.dependency_overrides.clear()
        with suppress(Exception):
            engine.dispose()
        tmp.cleanup()


@pytest.fixture
async def client(test_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def db_session(test_app: FastAPI):
    override = test_app.dependency_overrides[get_session]
    generator = override()
    session = next(generator)
    try:
        yield session
    finally:
        with suppress(StopIteration):
            next(generator)
