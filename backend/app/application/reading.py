"""User-facing projections. Never serialize ORM task snapshots or tool arguments."""

from datetime import date, datetime

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.application.profiles import LOCAL_USER_ID
from app.models.brief import BriefRecord, TaskRunRecord
from app.models.delivery import MailDeliveryRecord
from app.schemas.brief import BriefContent, BriefRead
from app.schemas.mail import DeliveryRead
from app.schemas.tasks import RunStatusRead


class ReadingBrief(BriefRead):
    delivery: DeliveryRead | None


class HistoryEntry(RunStatusRead):
    brief_id: int | None
    item_count: int | None
    delivery: DeliveryRead | None


class HistoryPage(BaseModel):
    items: list[HistoryEntry]
    has_more: bool


class WorkspaceStatus(BaseModel):
    profile_configured: bool
    preferences_configured: bool
    smtp_configured: bool
    scheduler_running: bool
    next_run_at: datetime | None
    latest_run: RunStatusRead | None
    active_run: RunStatusRead | None


def run_status(run: TaskRunRecord) -> RunStatusRead:
    return RunStatusRead(
        run_id=run.id,
        report_date=run.report_date,
        status=run.status,
        error_code=run.error_code,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


def delivery_status(record: MailDeliveryRecord | None) -> DeliveryRead | None:
    if record is None:
        return None
    return DeliveryRead(
        brief_id=record.brief_id,
        status=record.status,
        attempt_count=record.attempt_count,
        last_error_code=record.last_error_code,
    )


def reading_brief(session: Session, brief_id: int | None = None) -> ReadingBrief | None:
    query = (
        select(BriefRecord, TaskRunRecord, MailDeliveryRecord)
        .join(TaskRunRecord, TaskRunRecord.id == BriefRecord.run_id)
        .outerjoin(MailDeliveryRecord, MailDeliveryRecord.brief_id == BriefRecord.id)
        .where(TaskRunRecord.user_id == LOCAL_USER_ID)
    )
    if brief_id is not None:
        query = query.where(BriefRecord.id == brief_id)
    row = session.execute(
        query.order_by(BriefRecord.report_date.desc(), BriefRecord.id.desc()).limit(1)
    ).first()
    if row is None:
        if brief_id is not None:
            raise HTTPException(status_code=404, detail="brief_not_found")
        return None
    brief, run, delivery = row
    content = BriefContent.model_validate(brief.content_json)
    return ReadingBrief(
        id=brief.id,
        run_id=run.id,
        run_status=run.status,
        **content.model_dump(),
        delivery=delivery_status(delivery),
    )


def history_page(
    session: Session, report_date: date | None, offset: int, limit: int
) -> HistoryPage:
    query = (
        select(TaskRunRecord, BriefRecord, MailDeliveryRecord)
        .outerjoin(BriefRecord, BriefRecord.run_id == TaskRunRecord.id)
        .outerjoin(MailDeliveryRecord, MailDeliveryRecord.brief_id == BriefRecord.id)
        .where(TaskRunRecord.user_id == LOCAL_USER_ID)
    )
    if report_date is not None:
        query = query.where(TaskRunRecord.report_date == report_date)
    rows = session.execute(
        query.order_by(TaskRunRecord.started_at.desc(), TaskRunRecord.id.desc())
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return HistoryPage(
        items=[
            HistoryEntry(
                **run_status(run).model_dump(),
                brief_id=brief.id if brief else None,
                item_count=brief.content_json.get("item_count") if brief else None,
                delivery=delivery_status(delivery),
            )
            for run, brief, delivery in rows[:limit]
        ],
        has_more=len(rows) > limit,
    )
