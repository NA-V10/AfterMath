"""Application settings, loaded from environment variables (and the repo-level .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

APP_VERSION = "0.1.0"
API_PREFIX = "/api/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    aftermath_env: Literal["development", "test", "production"] = "development"
    database_url: str = (
        "postgresql+asyncpg://aftermath:change-me-local-only@localhost:5432/aftermath"
    )
    db_pool_size: int = Field(default=5, ge=1, le=50)
    api_cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    log_json: bool | None = None  # default: JSON outside development
    data_dir: Path = REPO_ROOT / "data"
    dataset_name: str = "meridian-valley"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def dataset_dir(self) -> Path:
        return self.data_dir / "synthetic" / self.dataset_name

    @property
    def scenarios_dir(self) -> Path:
        return self.data_dir / "scenarios"

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.aftermath_env != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
