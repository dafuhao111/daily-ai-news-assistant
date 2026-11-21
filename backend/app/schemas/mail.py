from typing import Literal

from pydantic import BaseModel, ConfigDict


class MailTestRead(BaseModel):
    status: Literal["pending", "succeeded", "failed"]
    error_code: str | None = None
    provider_reference: str | None = None


class DeliveryRead(BaseModel):
    brief_id: int
    status: Literal["pending", "sending", "submitted", "failed", "unknown", "skipped"]
    attempt_count: int
    last_error_code: str | None


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
