from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    app_env: str = "development"
    api_prefix: str = "/api/v1"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str | None = None
    agent_model_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    agent_max_tool_rounds: int = Field(default=8, ge=1, le=32)
    agent_max_calls_per_round: int = Field(default=8, ge=1, le=32)
    agent_task_timeout_seconds: float = Field(default=300.0, gt=0, le=900)


@lru_cache
def get_settings() -> Settings:
    return Settings()
