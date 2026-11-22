"""Opt-in concurrency checks on disposable records in the configured MySQL schema.

Never use a real recipient or SMTP implementation. No database/schema is dropped.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, delete, select

from app.application.briefs import BriefGenerationError, BriefGenerationService
from app.application.deliveries import MailDeliveryService
from app.application.tasks import TaskCoordinator
from app.core.config import Settings
from app.db.session import build_session_factory
from app.models.brief import BriefRecord, TaskRunRecord, ToolCallRecord
from app.models.delivery import MailDeliveryRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile
from app.schemas.preferences import PreferencesWrite

pytestmark = pytest.mark.mysql


@pytest.fixture
def mysql_records():
    if os.getenv("RUN_MYSQL_TESTS") != "1":
        pytest.skip("set RUN_MYSQL_TESTS=1 for disposable-record MySQL concurrency checks")
    settings = Settings()
    if not (settings.database_url or "").startswith("mysql+pymysql:"):
        pytest.fail("RUN_MYSQL_TESTS requires configured MySQL; no fallback database")
    engine = create_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )
    factory = build_session_factory(engine)
    token = uuid4().hex
    # OS randomness plus PK uniqueness; never touch the local user's id=1.
    user_id = 1_000_000_000 + int(token[:7], 16)
    payload = PreferencesWrite(
        topics=["Agent 与工具"],
        keywords=[],
        excluded_keywords=[],
        run_time=time(0, 0),
        timezone="Asia/Shanghai",
        enabled=False,
    )
    with factory.begin() as session:
        session.add(
            UserProfile(
                id=user_id,
                display_name="Disposable acceptance record",
                recipient_email="acceptance@example.org",
                mail_test_status="succeeded",
            )
        )
        session.flush()
        session.add(SubscriptionPreferences(user_id=user_id, **payload.model_dump()))

    class NeverSend:
        is_configured = True

        def send_brief(self, *_args):
            raise AssertionError("MySQL acceptance must never contact SMTP")

    delivery = MailDeliveryService(factory, settings, NeverSend())
    coordinator = TaskCoordinator(factory, settings, delivery)
    try:
        yield factory, coordinator, user_id, payload
    finally:
        with factory.begin() as session:
            run_ids = list(
                session.scalars(select(TaskRunRecord.id).where(TaskRunRecord.user_id == user_id))
            )
            brief_ids = list(
                session.scalars(select(BriefRecord.id).where(BriefRecord.run_id.in_(run_ids)))
            )
            session.execute(
                delete(MailDeliveryRecord).where(MailDeliveryRecord.brief_id.in_(brief_ids))
            )
            session.execute(delete(BriefRecord).where(BriefRecord.run_id.in_(run_ids)))
            session.execute(delete(ToolCallRecord).where(ToolCallRecord.run_id.in_(run_ids)))
            session.execute(delete(TaskRunRecord).where(TaskRunRecord.user_id == user_id))
            session.execute(
                delete(SubscriptionPreferences).where(SubscriptionPreferences.user_id == user_id)
            )
            session.execute(delete(UserProfile).where(UserProfile.id == user_id))
        engine.dispose()


def test_mysql_concurrent_clicks_and_schedule_share_one_slot(mysql_records):
    factory, coordinator, user_id, _payload = mysql_records
    with factory.begin() as session:
        session.get(SubscriptionPreferences, user_id).enabled = True
    barrier = threading.Barrier(8)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))

    def enqueue(index):
        barrier.wait(timeout=10)
        return (
            coordinator.enqueue_manual(user_id, f"click-{index}")
            if index % 2
            else coordinator.enqueue_scheduled(user_id, now)
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(enqueue, range(8)))
    with factory() as session:
        runs = list(session.scalars(select(TaskRunRecord).where(TaskRunRecord.user_id == user_id)))
    assert len(runs) == 1
    assert {result.run_id for result in results if result is not None} == {runs[0].id}


def test_mysql_atomic_execution_claim_has_only_one_winner(mysql_records):
    factory, coordinator, user_id, payload = mysql_records
    queued = coordinator.enqueue_manual(user_id, "claim-once")
    barrier = threading.Barrier(8)
    generator = BriefGenerationService(None, factory)
    with factory() as session:
        day = session.get(TaskRunRecord, queued.run_id).report_date

    def claim(_index):
        barrier.wait(timeout=10)
        try:
            generator._start_run(
                queued.run_id,
                user_id,
                "manual",
                f"manual:{user_id}:claim-once",
                day,
                payload.model_dump(mode="json"),
            )
            return "claimed"
        except BriefGenerationError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(claim, range(8)))
    assert outcomes.count("claimed") == 1
    assert outcomes.count("run_already_exists") == 7
    with factory() as session:
        run = session.get(TaskRunRecord, queued.run_id)
        assert run.status == "running" and run.attempt_count == 1


def test_mysql_concurrent_delivery_claim_and_retry_are_bounded(mysql_records):
    factory, coordinator, user_id, _payload = mysql_records
    queued = coordinator.enqueue_manual(user_id, "delivery-once")
    with factory.begin() as session:
        session.get(SubscriptionPreferences, user_id).enabled = True
        session.get(TaskRunRecord, queued.run_id).status = "completed"
        brief = BriefRecord(
            run_id=queued.run_id,
            report_date=datetime.now(ZoneInfo("Asia/Shanghai")).date(),
            content_json={
                "report_date": "2026-11-22",
                "generated_at": "2026-11-22T00:00:00Z",
                "item_count": 0,
                "items": [],
                "empty_reason": "test-only empty data",
            },
        )
        session.add(brief)
        session.flush()
        delivery = MailDeliveryRecord(
            brief_id=brief.id,
            recipient_snapshot="acceptance@example.org",
            status="pending",
            idempotency_key=f"disposable:{uuid4().hex}",
        )
        session.add(delivery)
        session.flush()
        delivery_id, brief_id = delivery.id, brief.id
    barrier = threading.Barrier(8)
    service = coordinator.delivery_service

    def claim(_index):
        barrier.wait(timeout=10)
        return service._claim(delivery_id) is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(claim, range(8)))
    assert outcomes.count(True) == 1
    with factory.begin() as session:
        record = session.get(MailDeliveryRecord, delivery_id)
        assert record.attempt_count == 1
        record.status = "failed"
    from app.application.deliveries import DeliveryError

    barrier = threading.Barrier(8)

    def retry(_index):
        barrier.wait(timeout=10)
        try:
            return service.request_retry(brief_id, user_id)
        except DeliveryError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        retries = list(pool.map(retry, range(8)))
    assert sum(result is not None for result in retries) == 1
    with factory() as session:
        assert session.get(MailDeliveryRecord, delivery_id).manual_retry_count == 1


def test_mysql_acceptance_restoration_uses_persisted_time_precision(mysql_records):
    from app.acceptance import restore_enabled
    from app.application.tasks import _preference_payload

    factory, _coordinator, user_id, _payload = mysql_records
    with factory.begin() as session:
        saved = session.get(SubscriptionPreferences, user_id)
        saved.enabled = True
        session.flush()
        session.refresh(saved)
        persisted_time = saved.updated_at
        snapshot = _preference_payload(saved)
    assert restore_enabled(factory, user_id, persisted_time, snapshot, False)
    with factory.begin() as session:
        saved = session.get(SubscriptionPreferences, user_id)
        assert saved.enabled is False
        saved.keywords = ["concurrent user edit"]
    assert not restore_enabled(factory, user_id, persisted_time, snapshot, True)
    with factory() as session:
        assert session.get(SubscriptionPreferences, user_id).keywords == ["concurrent user edit"]
