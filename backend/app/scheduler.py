import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.application.deliveries import MailDeliveryService
from app.application.tasks import TaskCoordinator
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile

logger = logging.getLogger(__name__)
SCHEDULER_LOCK_NAME = "daily-ai-news-assistant-scheduler"


class DailyScheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        coordinator: TaskCoordinator,
        deliveries: MailDeliveryService,
        *,
        scheduler: AsyncIOScheduler | None = None,
        now=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.session_factory = session_factory
        self.coordinator = coordinator
        self.deliveries = deliveries
        self.scheduler = scheduler or AsyncIOScheduler(timezone=timezone.utc)
        self.now = now
        self._lock_connection = None
        self._is_leader = False
        self._background_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        self._is_leader = self._acquire_scheduler_lock()
        if not self._is_leader:
            logger.info("scheduler lock is held by another API process")
            return
        if not self.scheduler.running:
            self.scheduler.start()
        if not self.scheduler.get_job("mail-delivery-retries"):
            self.scheduler.add_job(
                self.deliveries.process_due_deliveries,
                "interval",
                seconds=30,
                id="mail-delivery-retries",
                coalesce=True,
                max_instances=1,
            )
        if not self.scheduler.get_job("refresh-daily-schedules"):
            self.scheduler.add_job(
                self.refresh,
                "interval",
                seconds=60,
                id="refresh-daily-schedules",
                coalesce=True,
                max_instances=1,
            )
        self.deliveries.recover_inflight_as_unknown()
        recovered = self.coordinator.recover_interrupted_today(self.now())
        recovered_set = set(recovered)
        for run_id in recovered:
            self._spawn(self.coordinator.execute_queued(run_id))
        await self.refresh()
        for user_id in self._enabled_user_ids():
            queued = self.coordinator.enqueue_scheduled(user_id, self.now())
            if queued is not None and queued.run_id not in recovered_set:
                self._spawn(self.coordinator.execute_queued(queued.run_id))

    async def refresh(self) -> None:
        if not self._is_leader:
            return
        if not self.deliveries.mailer.is_configured:
            for job in self.scheduler.get_jobs():
                if job.id.startswith("daily:"):
                    self.scheduler.remove_job(job.id)
            return
        try:
            with self.session_factory() as session:
                schedules = list(
                    session.execute(
                        select(
                            SubscriptionPreferences.user_id,
                            SubscriptionPreferences.run_time,
                            SubscriptionPreferences.timezone,
                        )
                        .join(UserProfile, UserProfile.id == SubscriptionPreferences.user_id)
                        .where(
                            SubscriptionPreferences.enabled.is_(True),
                            UserProfile.recipient_email.is_not(None),
                            UserProfile.mail_test_status == "succeeded",
                        )
                    )
                )
        except SQLAlchemyError as error:
            logger.warning("daily schedule refresh failed (%s)", type(error).__name__)
            return

        wanted = {f"daily:{user_id}" for user_id, _run_time, _timezone in schedules}
        for job in self.scheduler.get_jobs():
            if job.id.startswith("daily:") and job.id not in wanted:
                self.scheduler.remove_job(job.id)
        for user_id, run_time, timezone_name in schedules:
            try:
                zone = ZoneInfo(timezone_name)
                trigger = CronTrigger(
                    hour=run_time.hour,
                    minute=run_time.minute,
                    second=run_time.second,
                    timezone=zone,
                )
            except (ValueError, KeyError) as error:
                logger.warning(
                    "invalid user schedule (user_id=%s, error=%s)", user_id, type(error).__name__
                )
                continue
            self.scheduler.add_job(
                self._run_scheduled_user,
                trigger=trigger,
                args=[user_id],
                id=f"daily:{user_id}",
                name=f"daily-user-{user_id}",
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=3600,
            )

    async def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
        running_tasks = list(self._background_tasks)
        for task in running_tasks:
            task.cancel()
        if running_tasks:
            await asyncio.gather(*running_tasks, return_exceptions=True)
        self._background_tasks.clear()
        if self._lock_connection is not None:
            try:
                self._lock_connection.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": SCHEDULER_LOCK_NAME},
                )
                self._lock_connection.commit()
            except SQLAlchemyError as error:
                logger.warning("scheduler lock release failed (%s)", type(error).__name__)
            finally:
                self._lock_connection.close()
                self._lock_connection = None
        self._is_leader = False

    async def _run_scheduled_user(self, user_id: int) -> None:
        queued = self.coordinator.enqueue_scheduled(user_id, self.now())
        if queued is not None:
            await self.coordinator.execute_queued(queued.run_id)

    def _spawn(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _enabled_user_ids(self) -> list[int]:
        try:
            with self.session_factory() as session:
                return list(
                    session.scalars(
                        select(SubscriptionPreferences.user_id)
                        .join(UserProfile, UserProfile.id == SubscriptionPreferences.user_id)
                        .where(
                            SubscriptionPreferences.enabled.is_(True),
                            UserProfile.recipient_email.is_not(None),
                            UserProfile.mail_test_status == "succeeded",
                        )
                    )
                )
        except SQLAlchemyError as error:
            logger.warning("enabled schedule lookup failed (%s)", type(error).__name__)
            return []

    def _acquire_scheduler_lock(self) -> bool:
        connection = None
        try:
            with self.session_factory() as session:
                engine = session.get_bind()
            if engine.dialect.name != "mysql":
                return True
            connection = engine.connect()
            acquired = connection.execute(
                text("SELECT GET_LOCK(:lock_name, 0)"),
                {"lock_name": SCHEDULER_LOCK_NAME},
            ).scalar_one_or_none()
            connection.commit()
            if acquired == 1:
                self._lock_connection = connection
                return True
            connection.close()
            return False
        except SQLAlchemyError as error:
            if connection is not None:
                connection.close()
            logger.warning("scheduler lock acquisition failed (%s)", type(error).__name__)
            return False
