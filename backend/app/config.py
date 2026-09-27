"""Application configuration, loaded from the project-root .env file."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/config.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
CHROMA_DIR = DATA_DIR / "chroma"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""

    # Verified available on this key (2.5-flash / -flash-lite return 404 here).
    gemini_model: str = "gemini-3.8-flash"
    gemini_embed_model: str = "gemini-embedding-2"
    # gemini-embedding-2 natively returns 3072 dims; 768 is plenty for a single
    # course corpus and keeps the Chroma index small.
    embed_dimensions: int = 768

    database_url: str = f"sqlite:///{(DATA_DIR / 'app.db').as_posix()}"

    # Retrieval
    chunk_size: int = 1000
    chunk_overlap: int = 150
    retrieval_top_k: int = 12

    # Lecture planning
    min_segment_minutes: int = 2

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


@lru_cache
def get_settings() -> Settings:
    for d in (DATA_DIR, UPLOAD_DIR, CHROMA_DIR):
        d.mkdir(parents=True, exist_ok=True)
    return Settings()
