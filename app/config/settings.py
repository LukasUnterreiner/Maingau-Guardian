"""Environment-driven configuration.

Everything secret (AI key, admin token) comes from environment variables and is
never logged or returned by the API. Business parameters (discount rate, churn
increments, contact costs...) are NOT configured here: they are read from the
`value_assumptions` sheet of the workbook.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Data
    data_dir: Path = Field(default=PROJECT_ROOT / "data", alias="DATA_DIR")
    workbook_file: str = Field(default="maingau_nba_mockdata.xlsx", alias="WORKBOOK_FILE")
    event_stream_file: str = Field(default="event_stream_2026-10-01.jsonl", alias="EVENT_STREAM_FILE")
    # Snapshot timestamp of the master view, documented in the workbook README.
    snapshot_at: str = Field(default="2026-09-30 23:59:59", alias="SNAPSHOT_AT")
    # "latest" = replay the whole event stream; "snapshot" = ignore events; or an ISO timestamp.
    evaluation_as_of: str = Field(default="latest", alias="EVALUATION_AS_OF")

    # Persistence (SQLite decision log, approval states, runtime settings)
    runtime_dir: Path = Field(default=PROJECT_ROOT / "runtime", alias="RUNTIME_DIR")
    sqlite_file: str = Field(default="guardian.sqlite3", alias="SQLITE_FILE")

    # API
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:5173", alias="CORS_ORIGINS")
    admin_token: SecretStr | None = Field(default=None, alias="ADMIN_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Optional AI integration (protocol must be verified against provider docs)
    ai_api_key: SecretStr | None = Field(default=None, alias="AI_API_KEY")
    ai_base_url: str | None = Field(default=None, alias="AI_BASE_URL")
    ai_model: str | None = Field(default=None, alias="AI_MODEL")
    ai_protocol: str = Field(default="openai_chat_completions", alias="AI_PROTOCOL")
    ai_timeout_s: float = Field(default=20.0, alias="AI_TIMEOUT_S")

    @property
    def workbook_path(self) -> Path:
        return self.data_dir / self.workbook_file

    @property
    def event_stream_path(self) -> Path:
        return self.data_dir / self.event_stream_file

    @property
    def sqlite_path(self) -> Path:
        return self.runtime_dir / self.sqlite_file

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_api_key and self.ai_api_key.get_secret_value() and self.ai_base_url and self.ai_model)


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
