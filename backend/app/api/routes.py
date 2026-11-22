import logging
from datetime import date
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.application.budget import BudgetError, TokenBudgetService
from app.application.deliveries import DeliveryError
from app.application.mail_tests import MailTestError
from app.application.preferences import get_preferences, save_preferences
from app.application.profiles import get_profile, save_profile
from app.application.reading import (
    HistoryPage,
    ReadingBrief,
    WorkspaceStatus,
    history_page,
    reading_brief,
    run_status,
)
from app.application.tasks import LOCAL_USER_ID, TaskQueueError
from app.db.session import get_session
from app.models.brief import TaskRunRecord
from app.models.delivery import MailDeliveryRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile
from app.schemas.mail import DeliveryRead, EmptyRequest, MailTestRead
from app.schemas.preferences import PreferencesRead, PreferencesWrite
from app.schemas.profile import ProfileRead, ProfileWrite
from app.schemas.tasks import RunAccepted, RunStatusRead

logger = logging.getLogger(__name__)
router = APIRouter()
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/budget")
def read_token_budget(request: Request, _session: SessionDep):
    try:
        return TokenBudgetService(request.app.state.session_factory).status()
    except BudgetError as error:
        raise HTTPException(status_code=503, detail=error.code) from None


@router.get("/profile", response_model=ProfileRead)
def read_profile(session: SessionDep) -> UserProfile:
    return get_profile(session)


@router.put("/profile", response_model=ProfileRead)
async def update_profile(
    payload: ProfileWrite,
    request: Request,
    session: SessionDep,
) -> UserProfile:
    profile = save_profile(session, payload)
    scheduler = getattr(request.app.state, "daily_scheduler", None)
    if scheduler is not None:
        await scheduler.refresh()
    return profile


@router.get("/preferences", response_model=PreferencesRead)
def read_preferences(session: SessionDep) -> SubscriptionPreferences:
    return get_preferences(session)


@router.put("/preferences", response_model=PreferencesRead)
async def update_preferences(
    payload: PreferencesWrite,
    request: Request,
    session: SessionDep,
) -> SubscriptionPreferences:
    preferences = save_preferences(session, payload)
    scheduler = getattr(request.app.state, "daily_scheduler", None)
    if scheduler is not None:
        await scheduler.refresh()
    return preferences


@router.post("/runs", status_code=202, response_model=RunAccepted)
def create_manual_run(
    _payload: EmptyRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> RunAccepted:
    coordinator = getattr(request.app.state, "task_coordinator", None)
    if coordinator is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    try:
        queued = coordinator.enqueue_manual(LOCAL_USER_ID, idempotency_key)
    except TaskQueueError as error:
        status = 404 if error.code.endswith("not_configured") else 409
        raise HTTPException(status_code=status, detail=error.code) from None
    if queued.status == "queued":
        background_tasks.add_task(coordinator.execute_queued, queued.run_id)
    return RunAccepted(run_id=queued.run_id, status=queued.status)


@router.get("/runs/{run_id}", response_model=RunStatusRead)
def get_run_status(run_id: str, session: SessionDep) -> RunStatusRead:
    run = session.get(TaskRunRecord, run_id)
    if run is None or run.user_id != LOCAL_USER_ID:
        raise HTTPException(status_code=404, detail="run_not_found")
    return run_status(run)


@router.get("/briefs/latest", response_model=ReadingBrief | None)
def get_latest_brief(session: SessionDep) -> ReadingBrief | None:
    return reading_brief(session)


@router.get("/briefs/{brief_id}", response_model=ReadingBrief)
def get_brief(brief_id: int, session: SessionDep) -> ReadingBrief | None:
    return reading_brief(session, brief_id)


@router.get("/history", response_model=HistoryPage)
def get_history(
    session: SessionDep,
    report_date: date | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> HistoryPage:
    return history_page(session, report_date, offset, limit)


@router.get("/status", response_model=WorkspaceStatus)
def get_workspace_status(request: Request, session: SessionDep) -> WorkspaceStatus:
    runs = select(TaskRunRecord).where(TaskRunRecord.user_id == LOCAL_USER_ID)
    latest = session.scalar(
        runs.order_by(TaskRunRecord.started_at.desc(), TaskRunRecord.id.desc()).limit(1)
    )
    active = session.scalar(
        runs.where(TaskRunRecord.status.in_(("queued", "running")))
        .order_by(TaskRunRecord.started_at.desc())
        .limit(1)
    )
    daily = request.app.state.daily_scheduler
    scheduler = daily.scheduler if daily else None
    running = bool(scheduler and scheduler.running)
    job = scheduler.get_job(f"daily:{LOCAL_USER_ID}") if running else None
    mailer = request.app.state.smtp_mailer
    return WorkspaceStatus(
        profile_configured=session.get(UserProfile, LOCAL_USER_ID) is not None,
        preferences_configured=session.get(SubscriptionPreferences, LOCAL_USER_ID) is not None,
        smtp_configured=mailer.is_configured,
        scheduler_running=running,
        next_run_at=job.next_run_time if job else None,
        latest_run=run_status(latest) if latest else None,
        active_run=run_status(active) if active else None,
    )


@router.get("/mail/status")
def get_mail_status(request: Request, session: SessionDep) -> dict[str, str | bool | None]:
    profile = get_profile(session)
    mailer = getattr(request.app.state, "smtp_mailer", None)
    return {
        "mail_test_status": profile.mail_test_status,
        "mail_tested_at": profile.mail_tested_at.isoformat() if profile.mail_tested_at else None,
        "smtp_configured": bool(mailer and mailer.is_configured),
    }


@router.post("/mail/test", response_model=MailTestRead)
async def submit_mail_test(_payload: EmptyRequest, request: Request) -> MailTestRead:
    service = getattr(request.app.state, "mail_test_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    try:
        return await service.submit_test(LOCAL_USER_ID)
    except MailTestError as error:
        status = 404 if error.code == "profile_not_configured" else 409
        raise HTTPException(status_code=status, detail=error.code) from None


@router.post("/mail/test/confirm", response_model=MailTestRead)
async def confirm_mail_test_received(_payload: EmptyRequest, request: Request) -> MailTestRead:
    service = getattr(request.app.state, "mail_test_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    try:
        result = service.confirm_received(LOCAL_USER_ID)
        scheduler = getattr(request.app.state, "daily_scheduler", None)
        if scheduler is not None:
            await scheduler.refresh()
        return result
    except MailTestError as error:
        status = 404 if error.code == "recipient_not_configured" else 409
        raise HTTPException(status_code=status, detail=error.code) from None


@router.post("/briefs/{brief_id}/delivery/retry", status_code=202, response_model=DeliveryRead)
async def retry_delivery(
    brief_id: int,
    _payload: EmptyRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> DeliveryRead:
    delivery_service = getattr(request.app.state, "mail_delivery_service", None)
    if delivery_service is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    try:
        delivery_id = delivery_service.request_retry(brief_id, LOCAL_USER_ID)
    except DeliveryError as error:
        status = 404 if error.code == "delivery_not_found" else 409
        raise HTTPException(status_code=status, detail=error.code) from None
    background_tasks.add_task(delivery_service.process_delivery, delivery_id)
    with request.app.state.session_factory() as session:
        delivery = session.get(MailDeliveryRecord, delivery_id)
        if delivery is None:
            raise HTTPException(status_code=404, detail="delivery_not_found")
        return DeliveryRead(
            brief_id=brief_id,
            status=delivery.status,
            attempt_count=delivery.attempt_count,
            last_error_code=delivery.last_error_code,
        )


@router.get("/health")
def health(request: Request) -> dict[str, str]:
    factory = request.app.state.session_factory
    if factory is None:
        raise HTTPException(status_code=503, detail="database_not_configured")
    try:
        with factory() as session:
            session.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.warning("database health check failed (%s)", type(error).__name__)
        raise HTTPException(status_code=503, detail="database_unavailable") from None
    return {"status": "ok", "database": "connected"}
