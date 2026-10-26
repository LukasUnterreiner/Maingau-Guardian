"""Lighty environment-driven configuration.

Everything secret (AI key, admin token, employee tokens) comes from environment
variables and is never logged or returned by the API. Business parameters (discount rate, churn
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
    sqlite_file: str = Field(default="lighty.sqlite3", alias="SQLITE_FILE")

    # API
    cors_origins: str = Field(default="http://localhost:3000,http://localhost:5173", alias="CORS_ORIGINS")
    admin_token: SecretStr | None = Field(default=None, alias="ADMIN_TOKEN")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    # Compute all 750 decisions at startup so the dashboard answers instantly.
    warm_portfolio_on_startup: bool = Field(default=True, alias="WARM_PORTFOLIO_ON_STARTUP")

    # Optional AI integration (protocol must be verified against provider docs)
    ai_api_key: SecretStr | None = Field(default=None, alias="AI_API_KEY")
    ai_base_url: str | None = Field(default=None, alias="AI_BASE_URL")
    ai_model: str | None = Field(default=None, alias="AI_MODEL")
    ai_protocol: str = Field(default="openai_chat_completions", alias="AI_PROTOCOL")
    ai_timeout_s: float = Field(default=20.0, alias="AI_TIMEOUT_S")
    # A gateway that cannot be reached should not hold every request for AI_TIMEOUT_S.
    ai_connect_timeout_s: float = Field(default=5.0, ge=0.5, le=60, alias="AI_CONNECT_TIMEOUT_S")
    # After a network failure, skip AI calls for this long and answer deterministically right away.
    ai_cooldown_s: float = Field(default=120.0, ge=0, le=3600, alias="AI_COOLDOWN_S")
    # Request format details, so a gateway can be adapted without code changes once its docs are checked.
    ai_chat_path: str = Field(default="/chat/completions", alias="AI_CHAT_PATH")
    ai_auth_header: str = Field(default="Authorization", alias="AI_AUTH_HEADER")
    ai_auth_scheme: str = Field(default="Bearer", alias="AI_AUTH_SCHEME")
    ai_max_tokens: int = Field(default=700, ge=64, le=4000, alias="AI_MAX_TOKENS")

    # Employee copilot access control.
    # EMPLOYEE_TOKENS = "token:employee_id:role,..." with role service_agent | sales_agent | marketing | admin.
    employee_tokens: SecretStr | None = Field(default=None, alias="EMPLOYEE_TOKENS")
    # Local development only: accept X-Employee-Id / X-Employee-Role headers without a token.
    allow_dev_auth: bool = Field(default=False, alias="ALLOW_DEV_AUTH")
    # Also require an employee token on the older customer/marketing/AI endpoints (off for compatibility).
    protect_customer_endpoints: bool = Field(default=False, alias="PROTECT_CUSTOMER_ENDPOINTS")
    copilot_history_messages: int = Field(default=6, ge=0, le=20, alias="COPILOT_HISTORY_MESSAGES")
    copilot_max_turns: int = Field(default=40, ge=1, le=200, alias="COPILOT_MAX_TURNS")

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
