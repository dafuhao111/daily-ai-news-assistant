import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import EmailStr, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_agent_workspace_dir() -> str:
    if os.name == "nt":
        app_data = os.environ.get("LOCALAPPDATA")
        base = Path(app_data) if app_data else Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / ".local" / "share"
    return str(base / "DailyAINewsAssistant" / "workspaces")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    frontend_dist_dir: str | None = None
    rss_sources_file: str = "config/rss_sources.json"
    agent_workspace_dir: str = Field(default_factory=_default_agent_workspace_dir)
    scheduler_enabled: bool = True
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    llm_api_protocol: Literal["chat_completions", "responses"] = "chat_completions"
    llm_max_output_tokens: int = Field(default=2048, ge=128, le=16384)
    agent_model_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    agent_max_tool_rounds: int = Field(default=8, ge=1, le=32)
    agent_max_calls_per_round: int = Field(default=8, ge=1, le=32)
    agent_task_timeout_seconds: float = Field(default=300.0, gt=0, le=900)
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] | None = None
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_email: EmailStr | None = None
    smtp_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    smtp_max_attempts: int = Field(default=3, ge=1, le=8)
    smtp_retry_base_seconds: int = Field(default=60, ge=1, le=3600)


@lru_cache
def get_settings() -> Settings:
    return Settings()
