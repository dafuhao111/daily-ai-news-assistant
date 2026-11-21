import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest

from app.application.deliveries import DeliveryError, MailDeliveryService
from app.core.config import Settings
from app.delivery.smtp import SMTPDeliveryFailure
from app.models.brief import BriefRecord, TaskRunRecord
from app.models.delivery import MailDeliveryRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile, utc_now
from app.schemas.brief import BriefContent, BriefItem


class FakeMailer:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = []

    def send_brief(self, brief, recipient, idempotency_key):
        self.calls.append((brief.id, recipient, idempotency_key))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def save_brief(session_factory, run_id="run-delivery", recipient="reader@example.org") -> int:
    with session_factory.begin() as session:
        if session.get(UserProfile, 1) is None:
            session.add(
                UserProfile(
                    id=1,
                    display_name="Reader",
                    recipient_email=recipient,
                    mail_test_status="succeeded",
                )
            )
            session.flush()
        if session.get(SubscriptionPreferences, 1) is None:
            session.add(
                SubscriptionPreferences(
                    user_id=1,
                    topics=["Agent 与工具"],
                    keywords=[],
                    excluded_keywords=[],
                    run_time=datetime.strptime("08:30", "%H:%M").time(),
                    timezone="Asia/Shanghai",
                    enabled=True,
                )
            )
        session.add(
            TaskRunRecord(
                id=run_id,
                user_id=1,
                run_type="manual",
                idempotency_key=f"manual:{run_id}",
                report_date=date(2026, 11, 21),
                status="completed",
                preferences_snapshot={},
                finished_at=utc_now(),
            )
        )
        session.flush()
        content = BriefContent(
            report_date=date(2026, 11, 21),
            generated_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
            item_count=1,
            empty_reason=None,
            items=[
                BriefItem(
                    article_id="a" * 32,
                    title="Agent release",
                    summary="A concise summary.",
                    source_excerpt="Source evidence.",
                    relevance_reason="Matches the topic.",
                    source_id="example-ai",
                    source_name="Example Feed",
                    category="AI",
                    url="https://articles.example.test/story",
                    canonical_url="https://articles.example.test/story",
                    published_at_raw=None,
                    published_at_utc=None,
                    published_at_field=None,
                    fetched_at_utc="2026-11-21T00:00:00+00:00",
                )
            ],
        )
        record = BriefRecord(
            run_id=run_id,
            report_date=content.report_date,
            content_json=content.model_dump(mode="json"),
        )
        session.add(record)
        session.flush()
        return record.id


def delivery_service(session_factory, mailer, **settings_overrides):
    settings = Settings(
        smtp_max_attempts=2,
        smtp_retry_base_seconds=1,
        **settings_overrides,
    )
    return MailDeliveryService(session_factory, settings, mailer)


def read_delivery(session_factory, delivery_id):
    with session_factory() as session:
        return session.get(MailDeliveryRecord, delivery_id)


def test_submitted_delivery_is_not_sent_twice(session_factory) -> None:
    brief_id = save_brief(session_factory)
    mailer = FakeMailer(["<accepted@example.org>"])
    service = delivery_service(session_factory, mailer)
    delivery_id = service.create_for_brief(brief_id, "reader@example.org")
    assert service.create_for_brief(brief_id, "reader@example.org") == delivery_id

    assert asyncio.run(service.process_delivery(delivery_id)) == "submitted"
    assert asyncio.run(service.process_delivery(delivery_id)) == "submitted"

    record = read_delivery(session_factory, delivery_id)
    assert record.status == "submitted"
    assert record.attempt_count == 1
    assert record.provider_reference == "<accepted@example.org>"
    assert len(mailer.calls) == 1


def test_temporary_rejection_retries_but_unknown_result_does_not(session_factory) -> None:
    first_brief = save_brief(session_factory, "run-temporary")
    retry_mailer = FakeMailer(
        [SMTPDeliveryFailure("smtp_temporary_rejection", "retry"), "<accepted@example.org>"]
    )
    retry_service = delivery_service(session_factory, retry_mailer)
    retry_id = retry_service.create_for_brief(first_brief, "reader@example.org")
    assert asyncio.run(retry_service.process_delivery(retry_id)) == "pending"
    with session_factory.begin() as session:
        record = session.get(MailDeliveryRecord, retry_id)
        assert record.next_attempt_at is not None
        record.next_attempt_at = utc_now() - timedelta(seconds=1)
    assert asyncio.run(retry_service.process_delivery(retry_id)) == "submitted"
    assert read_delivery(session_factory, retry_id).attempt_count == 2

    second_brief = save_brief(session_factory, "run-unknown")
    unknown_mailer = FakeMailer([SMTPDeliveryFailure("smtp_result_unknown", "unknown")])
    unknown_service = delivery_service(session_factory, unknown_mailer)
    unknown_id = unknown_service.create_for_brief(second_brief, "reader@example.org")
    assert asyncio.run(unknown_service.process_delivery(unknown_id)) == "unknown"
    asyncio.run(unknown_service.process_due_deliveries())
    assert read_delivery(session_factory, unknown_id).status == "unknown"
    assert len(unknown_mailer.calls) == 1
    with pytest.raises(DeliveryError, match="delivery_result_unknown"):
        unknown_service.request_retry(second_brief)


def test_definite_failure_can_retry_saved_brief_only(session_factory) -> None:
    brief_id = save_brief(session_factory)
    mailer = FakeMailer(
        [SMTPDeliveryFailure("smtp_permanent_rejection", "failed"), "<retry@example.org>"]
    )
    service = delivery_service(session_factory, mailer)
    delivery_id = service.create_for_brief(brief_id, "reader@example.org")

    assert asyncio.run(service.process_delivery(delivery_id)) == "failed"
    assert service.request_retry(brief_id) == delivery_id
    assert asyncio.run(service.process_delivery(delivery_id)) == "submitted"
    record = read_delivery(session_factory, delivery_id)
    assert record.manual_retry_count == 1
    assert record.attempt_count == 1


def test_disabled_subscription_delivery_is_persisted_as_skipped(session_factory) -> None:
    brief_id = save_brief(session_factory)
    mailer = FakeMailer([])
    service = delivery_service(session_factory, mailer)
    delivery_id = service.create_for_brief(
        brief_id,
        "reader@example.org",
        skipped="subscription_disabled",
    )

    assert asyncio.run(service.process_delivery(delivery_id)) == "skipped"
    assert read_delivery(session_factory, delivery_id).last_error_code == "subscription_disabled"
    assert mailer.calls == []
