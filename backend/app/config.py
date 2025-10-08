from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "NutriTrack Backend"
    DB_URL: str = "sqlite:///./nutritrack.db"  # dev: SQLite-Datei im backend-Ordner

settings = Settings()
