from typing import Iterator
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./nutritrack.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},  # for SQLite + FastAPI
)


def init_db():
    # Import via the public `app` package alias so tables are registered once.
    from app.models import wearables  # noqa: F401
    from app.models import foods      # noqa: F401
    from app.models import meals      # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
