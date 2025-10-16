from __future__ import annotations

from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        # Required for SQLite when used with FastAPI in threaded servers.
        return {"check_same_thread": False}
    return {}


settings = get_settings()

engine = create_engine(
    settings.database_url,
    echo=settings.database_echo,
    connect_args=_sqlite_connect_args(settings.database_url),
)


def init_db() -> None:
    # Import models so SQLModel sees the metadata.
    from app import models  # noqa: WPS433  (import for side effect)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
