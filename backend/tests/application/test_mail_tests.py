import asyncio

import pytest

from app.application.mail_tests import MailTestError, MailTestService
from app.models.profile import UserProfile


class FakeMailer:
    def __init__(self, outcome="<test@example.org>") -> None:
        self.outcome = outcome
        self.recipients = []

    def send_test(self, recipient, _idempotency_key):
        self.recipients.append(recipient)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def create_profile(session_factory, recipient="reader@example.org") -> None:
    with session_factory.begin() as session:
        session.add(
            UserProfile(
                id=1,
                display_name="Reader",
                recipient_email=recipient,
                mail_test_status="unconfigured",
            )
        )


def test_mail_test_requires_user_confirmation_before_marking_verified(session_factory) -> None:
    create_profile(session_factory)
    mailer = FakeMailer()
    service = MailTestService(session_factory, mailer)

    submitted = asyncio.run(service.submit_test())
    with session_factory() as session:
        profile = session.get(UserProfile, 1)
    assert submitted.status == "pending"
    assert submitted.provider_reference is None
    assert mailer.recipients == ["reader@example.org"]
    assert profile.mail_test_status == "pending"
    assert profile.mail_tested_at is not None

    confirmed = service.confirm_received()
    with session_factory() as session:
        profile = session.get(UserProfile, 1)
    assert confirmed.status == "succeeded"
    assert profile.mail_test_status == "succeeded"


def test_failed_test_mail_does_not_allow_confirmation(session_factory) -> None:
    create_profile(session_factory)
    mailer = FakeMailer(RuntimeError("connection refused"))
    service = MailTestService(session_factory, mailer)

    result = asyncio.run(service.submit_test())

    assert result.status == "failed"
    assert result.error_code == "smtp_adapter_error"
    with session_factory() as session:
        profile = session.get(UserProfile, 1)
    assert profile.mail_test_status == "failed"
    with pytest.raises(MailTestError, match="mail_test_not_pending"):
        service.confirm_received()
