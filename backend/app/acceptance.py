"""Explicit one-shot live acceptance; never enabled by normal API startup.

uv run --locked python -m app.acceptance --live --send-verified-email
The user must authorize the single real email before running that command.
"""

import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.application.tasks import _preference_payload
from app.core.config import Settings
from app.diagnostics import inspect_run
from app.models.brief import TaskRunRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile


def restore_enabled(factory, user_id, changed_at, snapshot, original_enabled) -> bool:
    with factory.begin() as session:
        saved = session.scalar(
            select(SubscriptionPreferences)
            .where(SubscriptionPreferences.user_id == user_id)
            .with_for_update()
        )
        if (
            saved is not None
            and saved.updated_at == changed_at
            and _preference_payload(saved) == snapshot
        ):
            saved.enabled = original_enabled
            return True
    return False


async def run_acceptance(app, *, send_email: bool = False) -> dict:
    """An explicit test run may coexist with an already-completed daily slot.

    It uses the production coordinator/Agent/SMTP flow, never a scripted model
    sequence. Temporarily enabling the saved subscription is required only for
    the explicitly requested single send. No daily cron or retry sweep starts.
    """
    settings = app.state.settings
    if settings.scheduler_enabled or settings.smtp_max_attempts != 1:
        raise RuntimeError("acceptance_requires_scheduler_off_and_one_send_attempt")
    factory = app.state.session_factory
    if factory is None:
        raise RuntimeError("database_not_configured")
    token = f"acceptance-{uuid4()}"
    original_enabled = None
    changed_at = None
    scheduler = AsyncIOScheduler(timezone="UTC")
    completed = asyncio.Event()
    try:
        with factory.begin() as session:
            profile = session.scalar(
                select(UserProfile).where(UserProfile.id == 1).with_for_update()
            )
            saved = session.get(SubscriptionPreferences, 1)
            if profile is None or saved is None:
                raise RuntimeError("save_profile_and_preferences_first")
            active = session.scalar(
                select(TaskRunRecord.id)
                .where(
                    TaskRunRecord.user_id == 1,
                    TaskRunRecord.status.in_(("queued", "running")),
                )
                .limit(1)
            )
            if active is not None:
                raise RuntimeError("another_run_is_active")
            if send_email and (
                not profile.recipient_email
                or profile.mail_test_status != "succeeded"
                or not app.state.smtp_mailer.is_configured
            ):
                raise RuntimeError("saved_recipient_must_be_verified_and_smtp_configured")
            original_enabled = saved.enabled
            if send_email:
                saved.enabled = True
                session.flush()
                # MySQL DATETIME may truncate Python microseconds. Compare the
                # persisted timestamp on restoration, not the pre-roundtrip value.
                session.refresh(saved)
                changed_at = saved.updated_at
            snapshot = _preference_payload(saved)
            if not send_email:
                snapshot["enabled"] = False
            session.add(
                TaskRunRecord(
                    id=token,
                    user_id=1,
                    run_type="manual",
                    idempotency_key=f"manual:1:{token}",
                    report_date=datetime.now(ZoneInfo(saved.timezone)).date(),
                    status="queued",
                    preferences_snapshot=snapshot,
                )
            )

        async def execute_once():
            try:
                await app.state.task_coordinator.execute_queued(token)
            finally:
                completed.set()

        # A real timer starts the same backend coordinator; the Agent's internal
        # tool choices remain entirely model-driven. Not a persistent daily job.
        scheduler.add_job(
            execute_once,
            "date",
            run_date=datetime.now(timezone.utc) + timedelta(seconds=2),
            id=token,
            max_instances=1,
            misfire_grace_time=30,
        )
        scheduler.start()
        print(
            json.dumps(
                {"run_id": token, "trigger": "one_shot_timer", "send_authorized": send_email}
            ),
            flush=True,
        )
        await asyncio.wait_for(completed.wait(), settings.agent_task_timeout_seconds + 120)
        result = inspect_run(factory, token)
        with factory() as session:
            from app.models.brief import BriefRecord
            from app.models.delivery import MailDeliveryRecord

            brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == token))
            delivery = (
                session.scalar(
                    select(MailDeliveryRecord).where(MailDeliveryRecord.brief_id == brief.id)
                )
                if brief
                else None
            )
            result["brief_items"] = brief.content_json["item_count"] if brief else 0
            result["delivery_status"] = delivery.status if delivery else None
            result["delivery_attempts"] = delivery.attempt_count if delivery else 0
        return result
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        if original_enabled is not None and send_email:
            # Do not overwrite a concurrent user edit.
            restored = restore_enabled(factory, 1, changed_at, snapshot, original_enabled)
            print(json.dumps({"subscription_restore_applied": restored}), flush=True)
        app.state.task_coordinator._fail_queued(token, "acceptance_interrupted")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One explicitly authorized live model run and optional email"
    )
    parser.add_argument(
        "--live", action="store_true", help="Allow real LLM/RSS requests and provider charges"
    )
    parser.add_argument(
        "--send-verified-email",
        action="store_true",
        help="Authorize at most one SMTP attempt to the saved verified target",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; real requests are never implicit")
    from app.main import create_app

    settings = Settings().model_copy(update={"scheduler_enabled": False, "smtp_max_attempts": 1})
    app = create_app(settings)
    try:
        result = asyncio.run(run_acceptance(app, send_email=args.send_verified_email))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result["final_result"]["status"] != "completed" or (
            args.send_verified_email and result["delivery_status"] != "submitted"
        ):
            raise SystemExit(1)
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
