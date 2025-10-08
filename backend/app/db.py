from typing import Iterator
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./nutritrack.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},  # für SQLite + FastAPI
)

def init_db():
    from .models import wearables  # noqa: F401
    from .models import foods      # noqa: F401  ← hinzufügen
    from .models import meals      # noqa: F401  ← hinzufügen
    SQLModel.metadata.create_all(engine)

def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
