from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "DataPilot AI"
    app_env: str = "development"
    debug: bool = False
    secret_key: str = "development-only-change-me"
    access_token_minutes: int = 60 * 12

    # PostgreSQL in production (postgresql+psycopg://user:pw@host/db); SQLite for quick local dev.
    database_url: str = f"sqlite:///{ROOT / 'data' / 'app.db'}"
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    upload_directory: Path = ROOT / "data" / "uploads"
    processed_directory: Path = ROOT / "data" / "processed"
    report_directory: Path = ROOT / "storage" / "reports"

    max_upload_mb: int = 100
    max_query_rows: int = 10_000
    query_timeout_seconds: int = 30
    allow_registration: bool = True

    # Optional LLM. Without a key every agent uses deterministic logic.
    llm_provider: str = "none"  # none | anthropic | google
    llm_model: str = ""
    llm_temperature: float = 0.1
    anthropic_api_key: str = ""
    google_api_key: str = ""

    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("upload_directory", "processed_directory", "report_directory", mode="after")
    @classmethod
    def _abs_dirs(cls, v: Path) -> Path:
        # "./data/uploads" in .env must mean <project>/data/uploads regardless of where the server is launched
        return v if v.is_absolute() else (ROOT / v).resolve()

    @field_validator("database_url")
    @classmethod
    def _normalize_db(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql+psycopg://", 1)
        elif v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+psycopg://", 1)
        if v.startswith("sqlite:///./"):
            v = f"sqlite:///{ROOT / v[len('sqlite:///./'):]}"
        return v

    def ensure_dirs(self) -> None:
        for p in (self.upload_directory, self.processed_directory, self.report_directory):
            p.mkdir(parents=True, exist_ok=True)

    @property
    def llm_enabled(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.llm_provider == "google":
            return bool(self.google_api_key)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
