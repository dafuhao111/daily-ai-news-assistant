from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

TOPIC_OPTIONS = (
    "AI 与学习教育",
    "AI 与体育",
    "AI 与日常生活",
    "AI 与工作效率",
    "AI 与创作",
    "大模型与研究",
    "Agent 与工具",
    "开源项目",
    "AI 工程",
    "多模态",
    "行业动态",
)


def validate_terms(values: list[str]) -> list[str]:
    normalized = [value.strip() for value in values]
    if any(not value for value in normalized):
        raise ValueError("keywords_must_not_be_blank")
    if len({value.casefold() for value in normalized}) != len(normalized):
        raise ValueError("keywords_must_be_unique")
    return normalized


class PreferencesWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    topics: list[str] = Field(min_length=1, max_length=len(TOPIC_OPTIONS))
    keywords: list[str] = Field(default_factory=list, max_length=20)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=20)
    run_time: time
    timezone: str = Field(min_length=1, max_length=64)
    enabled: bool = False

    @field_validator("topics")
    @classmethod
    def topics_must_be_known_and_unique(cls, values: list[str]) -> list[str]:
        values = validate_terms(values)
        if any(value not in TOPIC_OPTIONS for value in values):
            raise ValueError("unknown_topic")
        return values

    @field_validator("keywords", "excluded_keywords")
    @classmethod
    def normalize_terms(cls, values: list[str]) -> list[str]:
        if any(len(value.strip()) > 80 for value in values):
            raise ValueError("keyword_too_long")
        return validate_terms(values)

    @field_validator("run_time")
    @classmethod
    def run_time_must_be_local_wall_clock(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("run_time_must_not_include_timezone")
        return value

    @field_validator("timezone")
    @classmethod
    def timezone_must_be_iana(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise ValueError("invalid_timezone") from error
        return value


class PreferencesRead(PreferencesWrite):
    updated_at: datetime
