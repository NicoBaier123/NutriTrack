from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = BACKEND_ROOT / ".env"
RAG_EMBED_URL = "http://localhost:8001/embed"

# Load environment variables as early as possible so Settings picks them up.
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_PATH),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NutriTrack API"
    app_version: str = "0.1.0"
    docs_url: str = "/docs"
    database_url: str = f"sqlite:///{(BACKEND_ROOT / 'nutritrack.db').as_posix()}"
    database_echo: bool = False
    advisor_llm_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
