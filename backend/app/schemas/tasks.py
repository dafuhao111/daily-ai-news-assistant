from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class RunAccepted(BaseModel):
    run_id: str
    status: str


class RunStatusRead(BaseModel):
    run_id: str
    report_date: date
    status: Literal["queued", "running", "completed", "empty", "failed", "limited"]
    error_code: str | None
    started_at: datetime | None = None
    finished_at: datetime | None
