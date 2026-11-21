from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ProfileWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    display_name: str = Field(min_length=1, max_length=80)
    role: str | None = Field(default=None, max_length=120)
    recipient_email: EmailStr | None = None

    @field_validator("display_name")
    @classmethod
    def display_name_is_not_blank(cls, value: str) -> str:
        if not value:
            raise ValueError("display_name_required")
        return value

    @field_validator("role", mode="before")
    @classmethod
    def empty_role_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("recipient_email", mode="before")
    @classmethod
    def empty_email_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value


class ProfileRead(BaseModel):
    display_name: str
    role: str | None
    recipient_email: str | None
    mail_test_status: Literal["unconfigured", "pending", "succeeded", "failed"]
    mail_tested_at: datetime | None
