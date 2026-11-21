import asyncio
import hashlib
import json
from datetime import date, datetime, time, timezone

import httpx
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.agent import AgentLimits, AgentRunner
from app.application.deliveries import MailDeliveryService
from app.application.tasks import TaskCoordinator
from app.core.config import Settings
from app.core.task_context import ToolContext
from app.models.brief import BriefRecord, TaskRunRecord, ToolCallRecord
from app.models.delivery import MailDeliveryRecord
from app.models.news import NewsItemRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile
from app.news.service import NewsService
from app.tools import create_default_registry


class ScriptedModel:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.messages = []
        self.before_response = None

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.messages.append(list(messages))
        if self.before_response is not None:
            self.before_response(len(self.messages))
        return self.responses.pop(0)


class FakeMailer:
    def __init__(self) -> None:
        self.sent = []
        self.is_configured = True

    def send_brief(self, brief, recipient, idempotency_key):
        self.sent.append((brief.id, recipient, idempotency_key))
        return f"<brief-{brief.id}@example.org>"


def article_id() -> str:
    canonical = "https://articles.example.test/news/agent?id=1"
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def fetch_rss_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "fetch_rss",
                "args": {"source_ids": ["example-ai"]},
                "id": "scheduled-rss",
                "type": "tool_call",
            }
        ],
    )


def final_brief() -> AIMessage:
    return AIMessage(
        content=json.dumps(
            {
                "items": [
                    {
                        "article_id": article_id(),
                        "summary": "该新闻介绍了 Agent 的一项新进展。",
                        "relevance_reason": "符合关注的 Agent 话题。",
                    }
                ],
                "empty_reason": None,
            },
            ensure_ascii=False,
        )
    )


def empty_brief() -> AIMessage:
    return AIMessage(
        content=json.dumps(
            {"items": [], "empty_reason": "今日暂无符合偏好的新闻。"},
            ensure_ascii=False,
        )
    )


def configure_user(session_factory, *, enabled=True) -> None:
    with session_factory.begin() as session:
        session.add(
            UserProfile(
                id=1,
                display_name="Reader",
                role="AI 工程师",
                recipient_email="reader@example.org",
                mail_test_status="succeeded",
            )
        )
        session.flush()
        session.add(
            SubscriptionPreferences(
                user_id=1,
                topics=["Agent 与工具"],
                keywords=["Agent"],
                excluded_keywords=[],
                run_time=time(8, 30),
                timezone="Asia/Shanghai",
                enabled=enabled,
            )
        )


def build_coordinator(
    session_factory,
    tmp_path,
    rss_source,
    response_handler,
    public_resolver,
    responses,
):
    settings = Settings(
        scheduler_enabled=False,
        agent_workspace_dir=str(tmp_path / "agent-workspaces"),
        smtp_max_attempts=2,
    )
    mailer = FakeMailer()
    delivery_service = MailDeliveryService(session_factory, settings, mailer)
    model = ScriptedModel(responses)

    def agent_factory(_settings, _registry):
        news = NewsService(
            transport=httpx.MockTransport(response_handler),
            resolver=public_resolver,
        )
        return AgentRunner(
            model,
            create_default_registry(news_service=news),
            limits=AgentLimits(model_timeout_seconds=1, max_tool_rounds=4, task_timeout_seconds=5),
        )

    def context_factory(run_id, workspace_root, _settings, repository):
        return ToolContext(
            run_id=run_id,
            workspace_root=workspace_root,
            news_sources=(rss_source,),
            news_repository=repository,
        )

    coordinator = TaskCoordinator(
        session_factory,
        settings,
        delivery_service,
        agent_factory=agent_factory,
        tool_context_factory=context_factory,
    )
    coordinator.test_model = model
    return coordinator, mailer


def empty_feed_response(_request):
    return httpx.Response(
        200,
        content=b"<rss version='2.0'><channel><title>Empty</title></channel></rss>",
    )


def test_scheduled_task_generates_and_submits_a_saved_brief(
    tmp_path,
    session_factory,
    rss_source,
    response_handler,
    public_resolver,
) -> None:
    configure_user(session_factory)
    coordinator, mailer = build_coordinator(
        session_factory,
        tmp_path,
        rss_source,
        response_handler,
        public_resolver,
        [fetch_rss_call(), final_brief()],
    )
    now = datetime(2026, 11, 21, 1, tzinfo=timezone.utc)

    early = coordinator.enqueue_scheduled(1, datetime(2026, 11, 21, 0, tzinfo=timezone.utc))
    queued = coordinator.enqueue_scheduled(1, now)
    duplicate = coordinator.enqueue_scheduled(1, now)
    assert early is None
    assert queued is not None and duplicate is not None
    assert queued.run_id == duplicate.run_id
    assert queued.run_id

    asyncio.run(coordinator.execute_queued(queued.run_id))

    with session_factory() as session:
        run = session.get(TaskRunRecord, queued.run_id)
        brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == queued.run_id))
        delivery = session.scalar(
            select(MailDeliveryRecord).where(MailDeliveryRecord.brief_id == brief.id)
        )
        item = session.scalar(
            select(NewsItemRecord).where(NewsItemRecord.article_id == article_id())
        )
    assert run.status == "completed"
    assert run.report_date == date(2026, 11, 21)
    assert brief is not None
    assert delivery.status == "submitted"
    assert item.included_at is not None
    assert mailer.sent == [(brief.id, "reader@example.org", f"brief:{brief.id}")]
    assert coordinator.enqueue_scheduled(1, now) is None


def test_disabled_subscription_neither_queues_nor_pushes(
    tmp_path,
    session_factory,
    rss_source,
    response_handler,
    public_resolver,
) -> None:
    configure_user(session_factory, enabled=False)
    coordinator, mailer = build_coordinator(
        session_factory,
        tmp_path,
        rss_source,
        response_handler,
        public_resolver,
        [fetch_rss_call(), final_brief()],
    )

    assert coordinator.enqueue_scheduled(1, datetime(2026, 11, 21, 1, tzinfo=timezone.utc)) is None
    with session_factory() as session:
        runs = list(session.scalars(select(TaskRunRecord)))
    assert runs == []
    assert mailer.sent == []


def test_scheduled_run_snapshots_are_isolated_by_user_id(
    tmp_path,
    session_factory,
    rss_source,
    response_handler,
    public_resolver,
) -> None:
    configure_user(session_factory)
    with session_factory.begin() as session:
        session.add(
            UserProfile(
                id=2,
                display_name="Second Reader",
                recipient_email="second@example.org",
                mail_test_status="succeeded",
            )
        )
        session.flush()
        session.add(
            SubscriptionPreferences(
                user_id=2,
                topics=["大模型与研究"],
                keywords=["Research"],
                excluded_keywords=[],
                run_time=time(8, 30),
                timezone="Asia/Shanghai",
                enabled=True,
            )
        )
    coordinator, _mailer = build_coordinator(
        session_factory,
        tmp_path,
        rss_source,
        empty_feed_response,
        public_resolver,
        [fetch_rss_call(), empty_brief(), fetch_rss_call(), empty_brief()],
    )
    now = datetime(2026, 11, 21, 1, tzinfo=timezone.utc)

    first = coordinator.enqueue_scheduled(1, now)
    second = coordinator.enqueue_scheduled(2, now)

    assert first is not None and second is not None
    assert first.run_id != second.run_id
    with session_factory() as session:
        first_run = session.get(TaskRunRecord, first.run_id)
        second_run = session.get(TaskRunRecord, second.run_id)
    assert first_run.user_id == 1
    assert second_run.user_id == 2
    assert first_run.preferences_snapshot["topics"] == ["Agent 与工具"]
    assert second_run.preferences_snapshot["topics"] == ["大模型与研究"]
    asyncio.run(coordinator.execute_queued(first.run_id))
    asyncio.run(coordinator.execute_queued(second.run_id))
    with session_factory() as session:
        first_run = session.get(TaskRunRecord, first.run_id)
        second_run = session.get(TaskRunRecord, second.run_id)
    assert first_run.status == second_run.status == "empty", (
        first_run.error_code,
        second_run.error_code,
    )
    first_prompt = coordinator.test_model.messages[0][1].content
    second_prompt = coordinator.test_model.messages[2][1].content
    assert '"topics":["Agent 与工具"]' in first_prompt
    assert '"topics":["大模型与研究"]' in second_prompt
    assert "reader@example.org" not in first_prompt + second_prompt


def test_recovery_resumes_today_queued_runs_and_preserves_prior_attempt_traces(
    session_factory,
    tmp_path,
    rss_source,
    response_handler,
    public_resolver,
) -> None:
    configure_user(session_factory)
    with session_factory.begin() as session:
        session.add(
            TaskRunRecord(
                id="interrupted-today",
                user_id=1,
                run_type="scheduled",
                idempotency_key="daily:1:2026-11-21",
                report_date=date(2026, 11, 21),
                status="running",
                attempt_count=1,
                preferences_snapshot={
                    "topics": ["Agent 与工具"],
                    "keywords": ["Agent"],
                    "excluded_keywords": [],
                    "run_time": "08:30:00",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                },
            )
        )
        session.add(
            TaskRunRecord(
                id="manual-queued",
                user_id=1,
                run_type="manual",
                idempotency_key="manual:1:click-1",
                report_date=date(2026, 11, 21),
                status="queued",
                attempt_count=0,
                preferences_snapshot={
                    "topics": ["Agent 与工具"],
                    "keywords": ["Agent"],
                    "excluded_keywords": [],
                    "run_time": "08:30:00",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                },
            )
        )
        session.flush()
        session.add(
            ToolCallRecord(
                run_id="interrupted-today",
                attempt=1,
                iteration=1,
                call_id="attempt-1-rss-call",
                tool_name="fetch_rss",
                args_redacted={},
                status="succeeded",
            )
        )
    coordinator, _mailer = build_coordinator(
        session_factory,
        tmp_path,
        rss_source,
        response_handler,
        public_resolver,
        [],
    )

    recovered = coordinator.recover_interrupted_today(
        datetime(2026, 11, 21, 1, tzinfo=timezone.utc)
    )

    assert set(recovered) == {"interrupted-today", "manual-queued"}
    with session_factory() as session:
        run = session.get(TaskRunRecord, "interrupted-today")
        trace = session.scalar(
            select(ToolCallRecord).where(ToolCallRecord.run_id == "interrupted-today")
        )
    assert run.status == "queued"
    assert run.attempt_count == 1
    assert trace is not None and trace.call_id == "attempt-1-rss-call"

    asyncio.run(coordinator.execute_queued("interrupted-today"))
    with session_factory() as session:
        retried_run = session.get(TaskRunRecord, "interrupted-today")
        preserved = list(
            session.scalars(
                select(ToolCallRecord)
                .where(ToolCallRecord.run_id == "interrupted-today")
                .order_by(ToolCallRecord.attempt)
            )
        )
    assert retried_run.status == "failed"
    assert retried_run.attempt_count == 2
    assert [(call.attempt, call.call_id) for call in preserved] == [(1, "attempt-1-rss-call")]


def test_subscription_change_during_generation_skips_delivery_to_old_recipient(
    tmp_path,
    session_factory,
    rss_source,
    response_handler,
    public_resolver,
) -> None:
    configure_user(session_factory)
    coordinator, mailer = build_coordinator(
        session_factory,
        tmp_path,
        rss_source,
        response_handler,
        public_resolver,
        [fetch_rss_call(), final_brief()],
    )

    def pause_and_change_target(model_turn: int) -> None:
        if model_turn != 2:
            return
        with session_factory.begin() as session:
            preferences = session.get(SubscriptionPreferences, 1)
            profile = session.get(UserProfile, 1)
            preferences.enabled = False
            profile.recipient_email = "new-reader@example.org"

    coordinator.test_model.before_response = pause_and_change_target
    queued = coordinator.enqueue_scheduled(1, datetime(2026, 11, 21, 1, tzinfo=timezone.utc))
    assert queued is not None

    asyncio.run(coordinator.execute_queued(queued.run_id))

    with session_factory() as session:
        brief = session.scalar(select(BriefRecord))
        delivery = session.scalar(select(MailDeliveryRecord))
    assert brief is not None
    assert delivery.status == "skipped"
    assert delivery.last_error_code == "subscription_disabled"
    assert delivery.recipient_snapshot == "new-reader@example.org"
    assert mailer.sent == []
