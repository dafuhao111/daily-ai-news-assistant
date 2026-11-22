import hashlib
import json

import httpx
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent import AgentRunner
from app.application.tasks import TaskCoordinator
from app.core.config import Settings
from app.core.task_context import ToolContext
from app.models.brief import ToolCallRecord
from app.news.service import NewsService
from app.tools import create_default_registry


def test_saved_preferences_to_real_agent_loop_to_history(
    client,
    local_headers,
    session_factory,
    tmp_path,
    rss_source,
    response_handler,
    public_resolver,
):
    class Model:
        def bind_tools(self, tools, **kwargs):
            assert len(tools) == 8
            return self

        async def ainvoke(self, messages):
            if not any(getattr(message, "type", None) == "tool" for message in messages):
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "fetch_rss",
                            "args": {"source_ids": ["example-ai"]},
                            "id": "llm-selected-rss",
                            "type": "tool_call",
                        }
                    ],
                )
            article_id = hashlib.sha256(
                b"https://articles.example.test/news/agent?id=1"
            ).hexdigest()[:32]
            return AIMessage(
                content=json.dumps(
                    {
                        "items": [
                            {
                                "article_id": article_id,
                                "summary": "新的 Agent 版本发布。",
                                "relevance_reason": "符合 Agent 工具方向。",
                            }
                        ],
                        "empty_reason": None,
                    }
                )
            )

    settings = Settings(scheduler_enabled=False, agent_workspace_dir=str(tmp_path))
    registry = create_default_registry(
        news_service=NewsService(
            transport=httpx.MockTransport(response_handler),
            resolver=public_resolver,
        )
    )

    def context_factory(run_id, workspace, settings, repository):
        repository.sync_sources((rss_source,))
        return ToolContext(
            run_id=run_id,
            workspace_root=workspace,
            news_sources=(rss_source,),
            news_repository=repository,
        )

    coordinator = TaskCoordinator(
        session_factory,
        settings,
        client.app.state.mail_delivery_service,
        agent_factory=lambda *_args: AgentRunner(Model(), registry),
        tool_context_factory=context_factory,
    )
    client.app.state.task_coordinator = coordinator
    assert (
        client.put(
            "/api/v1/profile", json={"display_name": "读者"}, headers=local_headers
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/v1/preferences",
            json={
                "topics": ["Agent 与工具"],
                "keywords": ["Agent"],
                "run_time": "08:30",
                "timezone": "Asia/Shanghai",
                "enabled": False,
            },
            headers=local_headers,
        ).status_code
        == 200
    )
    headers = {**local_headers, "Idempotency-Key": "integration-test"}
    accepted = client.post("/api/v1/runs", json={}, headers=headers).json()
    status = client.get(f"/api/v1/runs/{accepted['run_id']}", headers=local_headers).json()
    assert status["status"] == "completed"
    latest = client.get("/api/v1/briefs/latest", headers=local_headers).json()
    assert latest["items"][0]["source_name"] == rss_source.name
    assert latest["delivery"]["status"] == "skipped"
    assert latest["delivery"]["last_error_code"] == "subscription_disabled"
    history = client.get(
        f"/api/v1/history?report_date={status['report_date']}", headers=local_headers
    ).json()
    assert history["items"][0]["brief_id"] == latest["id"]
    assert client.get(f"/api/v1/briefs/{latest['id']}", headers=local_headers).json() == latest
    assert (
        client.post("/api/v1/runs", json={}, headers=headers).json()["run_id"] == accepted["run_id"]
    )
    with session_factory() as session:
        calls = list(session.scalars(select(ToolCallRecord)))
        assert [(call.call_id, call.tool_name) for call in calls] == [
            ("llm-selected-rss", "fetch_rss")
        ]
