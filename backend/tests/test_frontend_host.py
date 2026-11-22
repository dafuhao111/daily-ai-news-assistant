from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_built_frontend_and_api_share_local_origin(engine, tmp_path, local_headers):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        '<html lang="zh-CN"><body>Daily brief</body></html>', encoding="utf-8"
    )
    (tmp_path / ".env").write_text("test-only-private-value", encoding="utf-8")
    app = create_app(Settings(scheduler_enabled=False, frontend_dist_dir=str(dist)), engine)
    with TestClient(app) as client:
        response = client.get("/", headers=local_headers)
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "Daily brief" in response.text
        assert client.get("/api/v1/status", headers=local_headers).json()["latest_run"] is None
        assert client.get("/.env", headers=local_headers).status_code == 404
        assert client.get("/%2e%2e/.env", headers=local_headers).status_code == 404
        assert client.get("/", headers={"Host": "external.example.org"}).status_code == 400


def test_missing_build_keeps_api_available(engine, tmp_path, local_headers):
    app = create_app(
        Settings(scheduler_enabled=False, frontend_dist_dir=str(tmp_path / "missing")), engine
    )
    with TestClient(app) as client:
        assert client.get("/", headers=local_headers).status_code == 404
        assert client.get("/api/v1/health", headers=local_headers).status_code == 200
