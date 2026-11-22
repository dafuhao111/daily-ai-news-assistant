import smtplib
from datetime import date, datetime, timezone
from typing import ClassVar

import pytest

from app.core.config import Settings
from app.delivery.smtp import SMTPDeliveryFailure, SMTPMailer
from app.schemas.brief import BriefItem, BriefRead


class FakeSMTP:
    instances: ClassVar[list] = []

    def __init__(self, host, port, *, timeout, **_kwargs) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.message = None
        self.instances.append(self)

    def ehlo(self):
        return 250, b"ok"

    def starttls(self, **_kwargs):
        return 220, b"ready"

    def login(self, username, password):
        self.username = username
        self.password = password
        return 235, b"accepted"

    def send_message(self, message, *, to_addrs):
        self.message = message
        self.to_addrs = to_addrs
        return {}

    def quit(self):
        return 221, b"bye"

    def close(self):
        pass


def smtp_settings(**overrides) -> Settings:
    values = {
        "smtp_host": "smtp.provider.test",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "sender",
        "smtp_password": "local-secret",
        "smtp_from_email": "assistant@example.org",
    }
    return Settings(**(values | overrides))


def sample_brief() -> BriefRead:
    return BriefRead(
        id=5,
        run_id="run-5",
        run_status="completed",
        report_date=date(2026, 11, 21),
        generated_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
        item_count=1,
        empty_reason=None,
        items=[
            BriefItem(
                article_id="a" * 32,
                title="Agent release",
                summary="该消息介绍了一个新进展。",
                source_excerpt="Original feed evidence.",
                relevance_reason="符合关注方向。",
                source_id="example-ai",
                source_name="Example AI Feed",
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


def test_smtp_brief_uses_saved_target_and_deterministic_message_id(monkeypatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr("app.delivery.smtp.smtplib.SMTP", FakeSMTP)
    mailer = SMTPMailer(smtp_settings())

    assert mailer.send_brief(sample_brief(), "reader@example.org", "brief:5") is None
    assert mailer.send_brief(sample_brief(), "reader@example.org", "brief:5") is None

    fake = FakeSMTP.instances[0]
    assert fake.to_addrs == ["reader@example.org"]
    assert fake.message["To"] == "reader@example.org"
    assert fake.message["From"] == "assistant@example.org"
    assert fake.message["Message-ID"] == SMTPMailer._message_id("brief:5")
    body = fake.message.get_content()
    assert "Agent release" in body
    assert "Original feed evidence." not in body
    assert "发布时间未提供/无法确认" in body


def test_smtp_configuration_rejects_placeholder_and_insecure_authenticated_transport() -> None:
    assert not SMTPMailer(smtp_settings(smtp_host="smtp.example.com")).is_configured
    assert not SMTPMailer(smtp_settings(smtp_security="none")).is_configured
    assert not SMTPMailer(smtp_settings(smtp_password=None)).is_configured


def test_disconnect_during_message_submission_is_unknown_not_retryable(monkeypatch) -> None:
    class DisconnectingSMTP(FakeSMTP):
        def send_message(self, _message, *, to_addrs):
            raise smtplib.SMTPServerDisconnected("connection closed after DATA")

    monkeypatch.setattr("app.delivery.smtp.smtplib.SMTP", DisconnectingSMTP)
    mailer = SMTPMailer(smtp_settings(smtp_security="none", smtp_username=None, smtp_password=None))

    with pytest.raises(SMTPDeliveryFailure) as error:
        mailer.send_test("reader@example.org", "test:disconnect")

    assert error.value.code == "smtp_result_unknown"
    assert error.value.disposition == "unknown"


def test_temporary_single_recipient_refusal_is_retryable(monkeypatch) -> None:
    class TemporaryRefusalSMTP(FakeSMTP):
        def send_message(self, _message, *, to_addrs):
            return {to_addrs[0]: (451, b"temporary mailbox failure")}

    monkeypatch.setattr("app.delivery.smtp.smtplib.SMTP", TemporaryRefusalSMTP)
    mailer = SMTPMailer(smtp_settings())

    with pytest.raises(SMTPDeliveryFailure) as error:
        mailer.send_test("reader@example.org", "test:temporary-refusal")

    assert error.value.disposition == "retry"
    assert error.value.code == "smtp_temporary_rejection"


def test_connection_timeout_is_retryable_but_data_timeout_is_unknown(monkeypatch):
    def connect_timeout(*_args, **_kwargs):
        raise TimeoutError("test-only timeout")

    monkeypatch.setattr("app.delivery.smtp.smtplib.SMTP", connect_timeout)
    with pytest.raises(SMTPDeliveryFailure) as connected:
        SMTPMailer(smtp_settings()).send_test("reader@example.org", "timeout-before-send")
    assert connected.value.disposition == "retry"
    assert connected.value.code == "smtp_connection_failed"

    class DataTimeout(FakeSMTP):
        def send_message(self, *_args, **_kwargs):
            raise TimeoutError("test-only DATA timeout")

    monkeypatch.setattr("app.delivery.smtp.smtplib.SMTP", DataTimeout)
    with pytest.raises(SMTPDeliveryFailure) as submitted:
        SMTPMailer(smtp_settings()).send_test("reader@example.org", "timeout-after-data")
    assert submitted.value.disposition == "unknown"
    assert submitted.value.code == "smtp_result_unknown"
