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
        env_ignore_empty=True,
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
    github_api_version: str = "2026-03-10"
    github_app_id: str | None = None
    github_app_private_key_path: Path | None = None
    github_app_private_key: str | None = None
    github_webhook_secret: str | None = None
    github_publishing_enabled: bool = False
    publish_confirmation_token: str | None = None
    allowed_repositories: str = ""
    review_policies_path: Path = Path("config/review-policies.json")
    worker_enabled: bool = True
    worker_poll_seconds: float = Field(default=2.0, ge=0.25, le=60)
    worker_max_attempts: int = Field(default=3, ge=1, le=10)
    worker_lease_seconds: int = Field(default=300, ge=30, le=3_600)
    webhook_max_bytes: int = Field(default=1_000_000, ge=1_000, le=5_000_000)
    dry_run_only: bool = True
    demo_mode_allowed: bool = True
    max_diff_chars: int = Field(default=60_000, ge=10_000, le=200_000)
    max_document_bytes: int = Field(default=1_000_000, ge=1_000, le=5_000_000)
    github_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    evaluation_dataset_path: Path = Path("evaluations/cases.json")
    evaluation_run_token: str | None = None
    openai_input_cost_per_million: float = Field(default=0.0, ge=0)
    openai_output_cost_per_million: float = Field(default=0.0, ge=0)
    log_level: str = "INFO"
    log_json: bool = True
    prompt_version: str = "phase4-v1"

    def resolve_path(self, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def resolved_database_path(self) -> Path:
        return self.resolve_path(self.database_path)

    @property
    def resolved_frontend_dist_path(self) -> Path:
        return self.resolve_path(self.frontend_dist_path)

    @property
    def resolved_review_policies_path(self) -> Path:
        return self.resolve_path(self.review_policies_path)

    @property
    def resolved_evaluation_dataset_path(self) -> Path:
        return self.resolve_path(self.evaluation_dataset_path)

    @property
    def allowed_repository_set(self) -> set[str]:
        return {
            item.strip().lower() for item in self.allowed_repositories.split(",") if item.strip()
        }

    @property
    def resolved_github_private_key(self) -> str | None:
        if self.github_app_private_key:
            return self.github_app_private_key.replace("\\n", "\n")
        if self.github_app_private_key_path:
            path = self.resolve_path(self.github_app_private_key_path)
            return path.read_text(encoding="utf-8")
        return None

    @property
    def github_app_ready(self) -> bool:
        return bool(self.github_app_id and self.resolved_github_private_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
