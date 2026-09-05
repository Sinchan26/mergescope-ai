from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "MergeScope AI"
    app_env: str = "development"
    debug: bool = False
    api_prefix: str = "/api"
    database_path: Path = Path("data/mergescope.db")
    frontend_dist_path: Path = Path("frontend/dist")
    openai_api_key: str | None = None
    openai_model: str = "gpt-6-astra"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=256, ge=64, le=1536)
    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    dry_run_only: bool = True
    demo_mode_allowed: bool = True
    max_diff_chars: int = Field(default=60_000, ge=10_000, le=200_000)
    max_document_bytes: int = Field(default=1_000_000, ge=1_000, le=5_000_000)
    github_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    prompt_version: str = "phase2-v1"

    def resolve_path(self, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def resolved_database_path(self) -> Path:
        return self.resolve_path(self.database_path)

    @property
    def resolved_frontend_dist_path(self) -> Path:
        return self.resolve_path(self.frontend_dist_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
