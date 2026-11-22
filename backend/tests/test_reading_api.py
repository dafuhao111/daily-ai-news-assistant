from datetime import date, datetime
from types import SimpleNamespace

from app.diagnostics import inspect_run
from app.models.brief import BriefRecord, TaskRunRecord, ToolCallRecord
from app.models.delivery import MailDeliveryRecord
from app.models.profile import UserProfile


def seed_history(session_factory):
    with session_factory.begin() as session:
        session.add_all(
            [UserProfile(id=1, display_name="Reader"), UserProfile(id=2, display_name="Other")]
        )
        session.flush()
        for index, user_id, status in [(1, 1, "empty"), (2, 1, "failed"), (3, 2, "empty")]:
            session.add(
                TaskRunRecord(
                    id=f"run-{index}",
                    user_id=user_id,
                    run_type="manual",
                    idempotency_key=f"key-{index}",
                    report_date=date(2026, 11, 22),
                    started_at=datetime(2026, 11, 22, index),
                    status=status,
                    error_code="model_timeout" if status == "failed" else None,
                    preferences_snapshot={"private": "never expose"},
                    usage_json={"private": "usage"},
                )
            )
            session.flush()
            if status == "empty":
                session.add(
                    BriefRecord(
                        id=index,
                        run_id=f"run-{index}",
                        report_date=date(2026, 11, 22),
                        content_json={
                            "report_date": "2026-11-22",
                            "generated_at": "2026-11-22T01:00:00Z",
                            "item_count": 0,
                            "items": [],
                            "empty_reason": "没有符合偏好的新闻。",
                        },
                    )
                )
        session.flush()
        session.add(
            MailDeliveryRecord(
                brief_id=1,
                status="failed",
                attempt_count=3,
                recipient_snapshot="private@example.org",
                idempotency_key="delivery-1",
                last_error_code="smtp_timeout",
                provider_reference="private provider",
            )
        )


def test_empty_workspace_and_input_validation(client, local_headers):
    assert client.get("/api/v1/briefs/latest", headers=local_headers).json() is None
    assert client.get("/api/v1/history", headers=local_headers).json() == {
        "items": [],
        "has_more": False,
    }
    status = client.get("/api/v1/status", headers=local_headers).json()
    assert status["profile_configured"] is False
    assert status["scheduler_running"] is False
    assert status["next_run_at"] is None
    for query in ("limit=0", "limit=101", "offset=-1", "report_date=bad"):
        assert client.get(f"/api/v1/history?{query}", headers=local_headers).status_code == 422


def test_history_latest_pagination_failures_and_ownership(client, local_headers, session_factory):
    seed_history(session_factory)
    first = client.get(
        "/api/v1/history?limit=1&report_date=2026-11-22", headers=local_headers
    ).json()
    assert first["has_more"] is True
    assert first["items"][0]["status"] == "failed"
    assert first["items"][0]["brief_id"] is None
    second = client.get("/api/v1/history?limit=1&offset=1", headers=local_headers).json()
    assert second["has_more"] is False
    assert second["items"][0]["delivery"]["last_error_code"] == "smtp_timeout"
    assert (
        client.get("/api/v1/history?report_date=2026-11-21", headers=local_headers).json()["items"]
        == []
    )
    latest = client.get("/api/v1/briefs/latest", headers=local_headers).json()
    assert latest["id"] == 1  # Latest failure preserves the previous brief.
    assert latest["empty_reason"] == "没有符合偏好的新闻。"
    assert latest == client.get("/api/v1/briefs/1", headers=local_headers).json()
    for path in ("briefs/3", "briefs/999", "runs/run-3"):
        assert client.get(f"/api/v1/{path}", headers=local_headers).status_code == 404
    serialized = str(first) + str(second) + str(latest)
    for secret in (
        "never expose",
        "private@example.org",
        "private provider",
        "usage_json",
        "preferences_snapshot",
    ):
        assert secret not in serialized
    status = client.get("/api/v1/status", headers=local_headers).json()
    assert status["latest_run"]["run_id"] == "run-2"
    assert status["active_run"] is None


def test_status_reports_actual_scheduler_job_and_active_run(client, local_headers, session_factory):
    seed_history(session_factory)
    with session_factory.begin() as session:
        session.get(TaskRunRecord, "run-1").status = "running"
    next_time = datetime.fromisoformat("2026-11-23T08:30:00+08:00")
    client.app.state.daily_scheduler = SimpleNamespace(
        scheduler=SimpleNamespace(
            running=True,
            get_job=lambda key: (
                SimpleNamespace(next_run_time=next_time) if key == "daily:1" else None
            ),
        )
    )
    status = client.get("/api/v1/status", headers=local_headers).json()
    assert status["next_run_at"] == "2026-11-23T08:30:00+08:00"
    assert status["active_run"]["run_id"] == "run-1"
    client.app.state.daily_scheduler = None


def test_developer_diagnostics_separates_model_calls_results_and_final_status(session_factory):
    seed_history(session_factory)
    with session_factory.begin() as session:
        session.add(
            ToolCallRecord(
                run_id="run-1",
                attempt=1,
                iteration=1,
                call_id="model-call-1",
                tool_name="fetch_rss",
                args_redacted={"private": "hidden args"},
                status="succeeded",
                result_summary="private tool content",
                duration_ms=5,
            )
        )
    result = inspect_run(session_factory, "run-1")
    assert result["model_tool_calls"][0]["call_id"] == "model-call-1"
    assert result["tool_results"][0]["status"] == "succeeded"
    assert result["final_result"] == {"status": "empty", "error_code": None, "brief_id": 1}
    assert "hidden args" not in str(result)
    assert "private tool content" not in str(result)
    assert inspect_run(session_factory, "run-3") == {"error": "run_not_found"}
