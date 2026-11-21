import asyncio
from datetime import datetime, time, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.application.deliveries import MailDeliveryService
from app.application.tasks import TaskCoordinator
from app.core.config import Settings
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile
from app.scheduler import DailyScheduler


def test_daily_job_uses_saved_iana_timezone_and_refreshes_preferences(session_factory) -> None:
    with session_factory.begin() as session:
        session.add(
            UserProfile(
                id=1,
                display_name="Reader",
                recipient_email="reader@example.org",
                mail_test_status="succeeded",
            )
        )
        session.flush()
        session.add(
            SubscriptionPreferences(
                user_id=1,
                topics=["Agent 与工具"],
                keywords=[],
                excluded_keywords=[],
                run_time=time(8, 30),
                timezone="Asia/Shanghai",
                enabled=True,
            )
        )
    settings = Settings(scheduler_enabled=False)

    class ConfiguredMailer:
        is_configured = True

    mailer = ConfiguredMailer()
    delivery = MailDeliveryService(session_factory, settings, mailer)
    coordinator = TaskCoordinator(session_factory, settings, delivery)
    scheduler = DailyScheduler(
        session_factory,
        coordinator,
        delivery,
        scheduler=AsyncIOScheduler(timezone="UTC"),
        now=lambda: datetime(2026, 11, 21, 0, tzinfo=timezone.utc),
    )

    async def check_jobs():
        await scheduler.start()
        try:
            first = scheduler.scheduler.get_job("daily:1")
            assert first is not None
            assert first.trigger.timezone.key == "Asia/Shanghai"
            with session_factory.begin() as session:
                preferences = session.get(SubscriptionPreferences, 1)
                preferences.run_time = time(9, 15)
                preferences.timezone = "America/New_York"
            await scheduler.refresh()
            updated = scheduler.scheduler.get_job("daily:1")
            assert updated is not None
            assert updated.trigger.timezone.key == "America/New_York"
            assert updated.trigger.fields[5].expressions[0].__str__() == "9"
        finally:
            await scheduler.shutdown()

    asyncio.run(check_jobs())
