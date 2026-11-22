import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.agent import create_agent
from app.application.briefs import BriefGenerationError, BriefGenerationService
from app.application.deliveries import DeliveryError, MailDeliveryService
from app.core.config import Settings
from app.core.task_context import ToolContext
from app.models.brief import BriefRecord, TaskRunRecord
from app.models.delivery import MailDeliveryRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile, utc_now
from app.news.context import create_tool_context
from app.news.repository import NewsRepository
from app.schemas.preferences import PreferencesWrite
from app.tools import create_default_registry

logger = logging.getLogger(__name__)
LOCAL_USER_ID = 1


class TaskQueueError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class QueuedRun:
    run_id: str
    status: str


def _preference_payload(preferences: SubscriptionPreferences) -> dict:
    return PreferencesWrite(
        topics=preferences.topics,
        keywords=preferences.keywords,
        excluded_keywords=preferences.excluded_keywords,
        run_time=preferences.run_time,
        timezone=preferences.timezone,
        enabled=preferences.enabled,
    ).model_dump(mode="json")


class TaskCoordinator:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        delivery_service: MailDeliveryService,
        *,
        agent_factory: Callable | None = None,
        tool_context_factory: Callable | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.delivery_service = delivery_service
        self.news_repository = NewsRepository(session_factory)
        self.agent_factory = agent_factory
        self.tool_context_factory = tool_context_factory

    def enqueue_manual(
        self,
        user_id: int = LOCAL_USER_ID,
        idempotency_token: str | None = None,
    ) -> QueuedRun:
        run_id = str(uuid4())
        try:
            with self.session_factory.begin() as session:
                profile = session.scalar(
                    select(UserProfile).where(UserProfile.id == user_id).with_for_update()
                )
                preferences = session.get(SubscriptionPreferences, user_id)
                if profile is None:
                    raise TaskQueueError("profile_not_configured")
                if preferences is None:
                    raise TaskQueueError("preferences_not_configured")
                local_date = datetime.now(ZoneInfo(preferences.timezone)).date()
                token = idempotency_token.strip() if idempotency_token else str(uuid4())
                if not token or len(token) > 80:
                    raise TaskQueueError("idempotency_key_invalid")
                key = f"manual:{user_id}:{token}"
                existing = session.scalar(
                    select(TaskRunRecord).where(TaskRunRecord.idempotency_key == key)
                )
                if existing is not None:
                    return QueuedRun(existing.id, existing.status)
                active = session.scalar(
                    select(TaskRunRecord)
                    .where(
                        TaskRunRecord.user_id == user_id,
                        # One active run per user, including across local midnight.
                        TaskRunRecord.run_type.in_(("manual", "scheduled")),
                        TaskRunRecord.status.in_(("queued", "running")),
                    )
                    .order_by(TaskRunRecord.started_at.desc())
                    .limit(1)
                )
                if active is not None:
                    return QueuedRun(active.id, active.status)
                completed = session.scalar(
                    select(TaskRunRecord)
                    .where(
                        TaskRunRecord.user_id == user_id,
                        TaskRunRecord.report_date == local_date,
                        TaskRunRecord.status.in_(("completed", "empty")),
                    )
                    .order_by(TaskRunRecord.started_at.desc())
                    .limit(1)
                )
                if completed is not None:
                    return QueuedRun(completed.id, completed.status)
                prior_delivery = session.scalar(
                    select(MailDeliveryRecord)
                    .join(BriefRecord, MailDeliveryRecord.brief_id == BriefRecord.id)
                    .join(TaskRunRecord, BriefRecord.run_id == TaskRunRecord.id)
                    .where(
                        TaskRunRecord.user_id == user_id,
                        TaskRunRecord.report_date == local_date,
                        MailDeliveryRecord.status.in_(
                            ("pending", "sending", "submitted", "unknown")
                        ),
                    )
                    .limit(1)
                )
                if prior_delivery is not None:
                    raise TaskQueueError("daily_delivery_already_exists")
                session.add(
                    TaskRunRecord(
                        id=run_id,
                        user_id=user_id,
                        run_type="manual",
                        idempotency_key=key,
                        report_date=local_date,
                        status="queued",
                        attempt_count=0,
                        preferences_snapshot=_preference_payload(preferences),
                    )
                )
        except TaskQueueError:
            raise
        except IntegrityError as error:
            logger.info("manual run already queued (user_id=%s)", user_id)
            raise TaskQueueError("run_already_queued") from error
        except SQLAlchemyError as error:
            logger.warning("manual run queue failed (%s)", type(error).__name__)
            raise TaskQueueError("database_unavailable") from error
        return QueuedRun(run_id, "queued")

    def enqueue_scheduled(
        self,
        user_id: int = LOCAL_USER_ID,
        now: datetime | None = None,
    ) -> QueuedRun | None:
        current = now or datetime.now(timezone.utc)
        try:
            with self.session_factory.begin() as session:
                profile = session.scalar(
                    select(UserProfile).where(UserProfile.id == user_id).with_for_update()
                )
                preferences = session.get(SubscriptionPreferences, user_id)
                if (
                    profile is None
                    or preferences is None
                    or not preferences.enabled
                    or not profile.recipient_email
                    or profile.mail_test_status != "succeeded"
                    or not self.delivery_service.mailer.is_configured
                ):
                    return None
                local_now = current.astimezone(ZoneInfo(preferences.timezone))
                if local_now.timetz().replace(tzinfo=None) < preferences.run_time:
                    return None
                report_date = local_now.date()
                key = f"daily:{user_id}:{report_date.isoformat()}"
                existing = session.scalar(
                    select(TaskRunRecord).where(TaskRunRecord.idempotency_key == key)
                )
                if existing is not None:
                    return (
                        QueuedRun(existing.id, existing.status)
                        if existing.status == "queued"
                        else None
                    )
                active = session.scalar(
                    select(TaskRunRecord.id)
                    .where(
                        TaskRunRecord.user_id == user_id,
                        TaskRunRecord.status.in_(("queued", "running")),
                    )
                    .limit(1)
                )
                if active is not None:
                    return None
                completed = session.scalar(
                    select(TaskRunRecord.id)
                    .where(
                        TaskRunRecord.user_id == user_id,
                        TaskRunRecord.report_date == report_date,
                        TaskRunRecord.status.in_(("completed", "empty")),
                    )
                    .limit(1)
                )
                if completed is not None:
                    return None
                prior_delivery = session.scalar(
                    select(MailDeliveryRecord.id)
                    .join(BriefRecord, MailDeliveryRecord.brief_id == BriefRecord.id)
                    .join(TaskRunRecord, BriefRecord.run_id == TaskRunRecord.id)
                    .where(
                        TaskRunRecord.user_id == user_id,
                        TaskRunRecord.report_date == report_date,
                        MailDeliveryRecord.status.in_(
                            ("pending", "sending", "submitted", "unknown")
                        ),
                    )
                    .limit(1)
                )
                if prior_delivery is not None:
                    return None
                run_id = str(uuid4())
                session.add(
                    TaskRunRecord(
                        id=run_id,
                        user_id=user_id,
                        run_type="scheduled",
                        idempotency_key=key,
                        report_date=report_date,
                        status="queued",
                        attempt_count=0,
                        preferences_snapshot=_preference_payload(preferences),
                    )
                )
        except IntegrityError:
            return None
        except SQLAlchemyError as error:
            logger.warning("scheduled run queue failed (%s)", type(error).__name__)
            return None
        return QueuedRun(run_id, "queued")

    def recover_interrupted_today(
        self, now: datetime | None = None, *, include_scheduled: bool = True
    ) -> list[str]:
        current = now or datetime.now(timezone.utc)
        recovered: list[str] = []
        try:
            with self.session_factory.begin() as session:
                runs = session.scalars(
                    select(TaskRunRecord).where(
                        TaskRunRecord.status.in_(("queued", "running")),
                    )
                )
                for run in runs:
                    if run.run_type == "scheduled" and not include_scheduled:
                        run.status = "failed"
                        run.error_code = "scheduler_disabled"
                        run.finished_at = utc_now()
                        continue
                    preferences = session.get(SubscriptionPreferences, run.user_id)
                    if preferences is None:
                        run.status = "failed"
                        run.error_code = "preferences_not_configured"
                        run.finished_at = utc_now()
                        continue
                    profile = session.get(UserProfile, run.user_id)
                    if run.run_type == "scheduled" and (
                        not preferences.enabled
                        or profile is None
                        or not profile.recipient_email
                        or profile.mail_test_status != "succeeded"
                        or not self.delivery_service.mailer.is_configured
                    ):
                        run.status = "failed"
                        run.error_code = "subscription_or_mail_disabled"
                        run.finished_at = utc_now()
                        continue
                    local_date = current.astimezone(ZoneInfo(preferences.timezone)).date()
                    if run.report_date == local_date:
                        if run.status == "running":
                            run.status = "queued"
                            run.error_code = None
                            run.finished_at = None
                        recovered.append(run.id)
                    elif run.report_date < local_date:
                        run.status = "failed"
                        run.error_code = "interrupted_previous_day"
                        run.finished_at = utc_now()
        except SQLAlchemyError as error:
            logger.warning("interrupted run recovery failed (%s)", type(error).__name__)
        return recovered

    async def execute_queued(self, run_id: str) -> None:
        try:
            with self.session_factory() as session:
                run = session.get(TaskRunRecord, run_id)
                if run is None or run.status != "queued":
                    return
                user_id = run.user_id
                run_type = run.run_type
                report_date = run.report_date
                idempotency_key = run.idempotency_key
                preferences = PreferencesWrite.model_validate(run.preferences_snapshot)
                profile = session.get(UserProfile, user_id)
                if profile is None:
                    failure_code = "profile_not_configured"
                elif run_type == "scheduled":
                    preferences_row = session.get(SubscriptionPreferences, user_id)
                    if (
                        preferences_row is None
                        or not preferences_row.enabled
                        or not profile.recipient_email
                        or profile.mail_test_status != "succeeded"
                    ):
                        failure_code = "subscription_or_mail_disabled"
                    else:
                        failure_code = None
                else:
                    failure_code = None
            if failure_code:
                self._fail_queued(run_id, failure_code)
                return

            workspace = self._workspace(run_id)
            context_factory = self.tool_context_factory or create_tool_context
            context: ToolContext = context_factory(
                run_id,
                workspace,
                self.settings,
                self.news_repository,
            )
            if self.agent_factory is not None:
                runner = self.agent_factory(self.settings, create_default_registry())
            else:
                runner = create_agent(self.settings, registry=create_default_registry())
            generator = BriefGenerationService(runner, self.session_factory)
            brief = await generator.generate(
                preferences,
                context,
                report_date,
                user_id=user_id,
                run_type=run_type,
                idempotency_key=idempotency_key,
                delivery_target_provider=lambda session: self._delivery_target(
                    session, user_id, preferences.enabled
                ),
            )
            if not brief.items:
                return
            delivery_id, delivery_status = self.delivery_service.get_for_brief(brief.id)
            if delivery_status == "pending":
                await self.delivery_service.process_delivery(delivery_id)
        except BriefGenerationError as error:
            if error.code == "run_already_exists":
                return  # Another claimant owns this execution; never alter its status.
            logger.info("queued run stopped (run_id=%s, error_code=%s)", run_id, error.code)
            self._fail_queued(run_id, error.code)
        except (TaskQueueError, DeliveryError) as error:
            logger.info("queued run stopped (run_id=%s)", run_id)
            self._fail_queued(run_id, error.code)
        except Exception as error:  # noqa: BLE001 - normalize orchestration failures
            logger.warning(
                "queued run failed (run_id=%s, error_type=%s)", run_id, type(error).__name__
            )
            self._fail_queued(run_id, "task_orchestration_failed")

    def _delivery_target(
        self, session: Session, user_id: int, enabled_snapshot: bool
    ) -> tuple[str | None, str | None]:
        profile = session.get(UserProfile, user_id)
        current_preferences = session.get(SubscriptionPreferences, user_id)
        if not enabled_snapshot or current_preferences is None or not current_preferences.enabled:
            return profile.recipient_email if profile else None, "subscription_disabled"
        if (
            profile is None
            or not profile.recipient_email
            or profile.mail_test_status != "succeeded"
        ):
            return profile.recipient_email if profile else None, "mail_not_verified"
        if not self.delivery_service.mailer.is_configured:
            return profile.recipient_email, "smtp_not_configured"
        return profile.recipient_email, None

    def _workspace(self, run_id: str) -> Path:
        root = Path(self.settings.agent_workspace_dir).resolve()
        workspace = (root / run_id).resolve()
        if not workspace.is_relative_to(root):
            raise TaskQueueError("workspace_path_denied")
        for directory in ("inputs", "history", "drafts"):
            (workspace / directory).mkdir(parents=True, exist_ok=True)
        return workspace

    def _fail_queued(self, run_id: str, error_code: str) -> None:
        try:
            with self.session_factory.begin() as session:
                run = session.get(TaskRunRecord, run_id)
                if run is not None and run.status == "queued":
                    run.status = "failed"
                    run.error_code = error_code[:64]
                    run.finished_at = utc_now()
        except SQLAlchemyError as error:
            logger.warning("queued run failure update failed (%s)", type(error).__name__)
