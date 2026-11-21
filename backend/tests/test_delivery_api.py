from datetime import date

from fastapi.testclient import TestClient

from app.application.mail_tests import MailTestService
from app.application.tasks import QueuedRun
from app.models.brief import BriefRecord, TaskRunRecord
from app.models.delivery import MailDeliveryRecord
from app.models.profile import UserProfile


class FakeMailer:
    is_configured = True

    def __init__(self) -> None:
        self.recipients = []

    def send_test(self, recipient, _idempotency_key):
        self.recipients.append(recipient)


class CoordinatorStub:
    def __init__(self) -> None:
        self.queued = []
        self.executed = []

    def enqueue_manual(self, user_id, idempotency_key):
        self.queued.append((user_id, idempotency_key))
        return QueuedRun("run-manual-test", "queued")

    async def execute_queued(self, run_id):
        self.executed.append(run_id)


def test_mail_test_uses_saved_target_and_requires_explicit_confirmation(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    client.put(
        "/api/v1/profile",
        json={"display_name": "Reader", "recipient_email": "reader@example.org"},
        headers=local_headers,
    )
    mailer = FakeMailer()
    client.app.state.mail_test_service = MailTestService(
        client.app.state.session_factory,
        mailer,
    )

    rejected = client.post(
        "/api/v1/mail/test",
        json={"recipient_email": "attacker@example.org"},
        headers=local_headers,
    )
    assert rejected.status_code == 422
    assert mailer.recipients == []

    submitted = client.post("/api/v1/mail/test", json={}, headers=local_headers)
    assert submitted.status_code == 200
    assert submitted.json() == {"status": "pending", "error_code": None, "provider_reference": None}
    assert mailer.recipients == ["reader@example.org"]
    with client.app.state.session_factory() as session:
        profile = session.get(UserProfile, 1)
    assert profile.mail_test_status == "pending"

    preferences = {
        "topics": ["Agent 与工具"],
        "run_time": "08:30",
        "timezone": "Asia/Shanghai",
        "enabled": True,
    }
    assert (
        client.put("/api/v1/preferences", json=preferences, headers=local_headers).status_code
        == 409
    )
    confirmed = client.post("/api/v1/mail/test/confirm", json={}, headers=local_headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "succeeded"
    assert (
        client.put("/api/v1/preferences", json=preferences, headers=local_headers).status_code
        == 200
    )


def test_manual_run_api_queues_background_work_once(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    coordinator = CoordinatorStub()
    client.app.state.task_coordinator = coordinator

    response = client.post(
        "/api/v1/runs",
        json={},
        headers={**local_headers, "Idempotency-Key": "manual-click-1"},
    )

    assert response.status_code == 202
    assert response.json() == {"run_id": "run-manual-test", "status": "queued"}
    assert coordinator.queued == [(1, "manual-click-1")]
    assert coordinator.executed == ["run-manual-test"]


def test_delivery_retry_api_uses_saved_brief_in_background(
    client: TestClient,
    local_headers: dict[str, str],
    session_factory,
) -> None:
    with session_factory.begin() as session:
        session.add(UserProfile(id=1, display_name="Reader"))
        session.flush()
        session.add(
            TaskRunRecord(
                id="retry-run",
                user_id=1,
                run_type="manual",
                idempotency_key="manual:retry-run",
                report_date=date(2026, 11, 21),
                status="completed",
                preferences_snapshot={},
            )
        )
        session.flush()
        brief = BriefRecord(
            run_id="retry-run",
            report_date=date(2026, 11, 21),
            content_json={},
        )
        session.add(brief)
        session.flush()
        delivery = MailDeliveryRecord(
            brief_id=brief.id,
            recipient_snapshot="reader@example.org",
            status="failed",
            attempt_count=1,
            manual_retry_count=0,
            last_error_code="smtp_permanent_rejection",
            idempotency_key=f"brief:{brief.id}",
        )
        session.add(delivery)
        session.flush()
        brief_id, delivery_id = brief.id, delivery.id

    class DeliveryStub:
        def __init__(self) -> None:
            self.called = []

        def request_retry(self, received_brief_id, user_id):
            assert received_brief_id == brief_id
            assert user_id == 1
            return delivery_id

        async def process_delivery(self, received_delivery_id):
            self.called.append(received_delivery_id)
            with session_factory.begin() as session:
                record = session.get(MailDeliveryRecord, received_delivery_id)
                record.status = "submitted"
            return "submitted"

    delivery_stub = DeliveryStub()
    client.app.state.mail_delivery_service = delivery_stub
    response = client.post(
        f"/api/v1/briefs/{brief_id}/delivery/retry",
        json={},
        headers=local_headers,
    )

    assert response.status_code == 202
    assert response.json()["brief_id"] == brief_id
    assert delivery_stub.called == [delivery_id]
