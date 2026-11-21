from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_profile_and_preferences_round_trip(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    profile_payload = {
        "display_name": "林同学",
        "role": "AI 工程学习者",
        "recipient_email": "reader@example.com",
    }
    response = client.put("/api/v1/profile", json=profile_payload, headers=local_headers)
    assert response.status_code == 200
    assert response.json() == {
        **profile_payload,
        "mail_test_status": "unconfigured",
        "mail_tested_at": None,
    }
    assert client.get("/api/v1/profile", headers=local_headers).json() == response.json()

    preferences_payload = {
        "topics": ["Agent 与工具", "AI 与工作效率"],
        "keywords": [" LangGraph ", "开源模型"],
        "excluded_keywords": ["营销"],
        "run_time": "08:30",
        "timezone": "Asia/Shanghai",
        "enabled": False,
    }
    response = client.put("/api/v1/preferences", json=preferences_payload, headers=local_headers)
    assert response.status_code == 200
    assert response.json()["keywords"] == ["LangGraph", "开源模型"]
    assert response.json()["run_time"] == "08:30:00"
    assert client.get("/api/v1/preferences", headers=local_headers).json() == response.json()


def test_get_unconfigured_records_returns_not_found(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    assert client.get("/api/v1/profile", headers=local_headers).status_code == 404
    assert client.get("/api/v1/preferences", headers=local_headers).status_code == 404


def test_preferences_require_profile_and_verified_mail_for_enable(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    preferences_payload = {
        "topics": ["Agent 与工具"],
        "run_time": "08:30",
        "timezone": "Asia/Shanghai",
        "enabled": False,
    }
    response = client.put("/api/v1/preferences", json=preferences_payload, headers=local_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "profile_not_configured"

    client.put(
        "/api/v1/profile",
        json={"display_name": "Lin", "recipient_email": "reader@example.com"},
        headers=local_headers,
    )
    preferences_payload["enabled"] = True
    response = client.put("/api/v1/preferences", json=preferences_payload, headers=local_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "mail_not_verified"


def test_profile_email_change_resets_mail_test_status(
    client: TestClient, local_headers: dict[str, str], session_factory
) -> None:
    client.put(
        "/api/v1/profile",
        json={"display_name": "Lin", "recipient_email": "reader@example.com"},
        headers=local_headers,
    )
    from app.models.profile import UserProfile

    with session_factory() as session:
        profile = session.get(UserProfile, 1)
        profile.mail_test_status = "succeeded"
        session.commit()

    response = client.put(
        "/api/v1/profile",
        json={"display_name": "Lin", "recipient_email": "new@example.com"},
        headers=local_headers,
    )
    assert response.status_code == 200
    assert response.json()["mail_test_status"] == "unconfigured"
    assert response.json()["mail_tested_at"] is None


def test_invalid_preferences_are_rejected(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    client.put(
        "/api/v1/profile",
        json={"display_name": "Lin"},
        headers=local_headers,
    )
    invalid_payloads = [
        {"topics": [], "run_time": "08:30", "timezone": "Asia/Shanghai"},
        {"topics": ["泛科技"], "run_time": "08:30", "timezone": "Asia/Shanghai"},
        {"topics": ["Agent 与工具"], "run_time": "25:90", "timezone": "Asia/Shanghai"},
        {"topics": ["Agent 与工具"], "run_time": "08:30", "timezone": "Mars/Olympus"},
        {"topics": ["Agent 与工具"], "run_time": "08:30+08:00", "timezone": "Asia/Shanghai"},
        {
            "topics": ["Agent 与工具"],
            "keywords": ["重复", "重复"],
            "run_time": "08:30",
            "timezone": "Asia/Shanghai",
        },
    ]
    for payload in invalid_payloads:
        response = client.put("/api/v1/preferences", json=payload, headers=local_headers)
        assert response.status_code == 422


def test_profile_validation_and_readiness(
    client: TestClient, local_headers: dict[str, str]
) -> None:
    for payload in (
        {"display_name": "  ", "recipient_email": "reader@example.com"},
        {"display_name": "Lin", "recipient_email": "not-an-email"},
    ):
        response = client.put("/api/v1/profile", json=payload, headers=local_headers)
        assert response.status_code == 422

    response = client.get("/api/v1/health", headers={"Host": "127.0.0.1"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}


def test_unconfigured_database_returns_service_unavailable(local_headers: dict[str, str]) -> None:
    app = create_app(settings=Settings(database_url=None))
    with TestClient(app) as client:
        response = client.get("/api/v1/profile", headers=local_headers)
    assert response.status_code == 503
    assert response.json() == {"detail": "database_not_configured"}
