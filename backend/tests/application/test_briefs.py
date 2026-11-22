import asyncio
import hashlib
import json
from datetime import date, time

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.agent import AgentLimits, AgentRunner
from app.application.briefs import BriefGenerationError, BriefGenerationService
from app.models.brief import BriefRecord, TaskRunRecord, ToolCallRecord
from app.models.delivery import MailDeliveryRecord
from app.models.news import NewsItemRecord
from app.models.profile import UserProfile, utc_now
from app.news.repository import NewsRepository
from app.news.schemas import NewsArticle
from app.news.service import NewsService
from app.schemas.preferences import PreferencesWrite
from app.tools import ToolContext, create_default_registry

REPORT_DATE = date(2026, 11, 21)


def article_id(path: str) -> str:
    canonical_url = f"https://articles.example.test{path}"
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:32]


class ScriptedModel:
    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = list(responses)
        self.messages = []

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.messages.append(list(messages))
        return self.responses.pop(0)


class PreferenceAwareModel:
    def __init__(self) -> None:
        self.messages = []

    def bind_tools(self, _tools, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.messages.append(list(messages))
        task_prompt = messages[1].content
        prefers_research = '"keywords":["Research"]' in task_prompt
        returned_tools = [
            message.name for message in messages if getattr(message, "type", None) == "tool"
        ]
        if "fetch_rss" not in returned_tools:
            return tool_call("fetch_rss", {"source_ids": ["example-ai"]}, "rss-selected")
        if prefers_research and "search_news" not in returned_tools:
            return tool_call("search_news", {"query": "Research", "limit": 5}, "search-selected")
        selected_path = "/news/research?id=2" if prefers_research else "/news/agent?id=1"
        return final_brief([article_id(selected_path)])


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def final_brief(article_ids: list[str]) -> AIMessage:
    payload = {
        "items": [
            {
                "article_id": value,
                "summary": "该消息介绍了一个与人工智能相关的新进展。",
                "relevance_reason": "符合订阅的话题方向。",
            }
            for value in article_ids
        ],
        "empty_reason": None if article_ids else "今日暂无符合偏好的新闻。",
    }
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


def preferences(
    *, topics: list[str] | None = None, keywords: list[str] | None = None, excluded=None
) -> PreferencesWrite:
    return PreferencesWrite(
        topics=topics or ["Agent 与工具"],
        keywords=keywords or ["Agent"],
        excluded_keywords=excluded or [],
        run_time=time(8, 30),
        timezone="Asia/Shanghai",
        enabled=False,
    )


def ensure_user(session_factory) -> None:
    with session_factory.begin() as session:
        session.add(
            UserProfile(
                id=1,
                display_name="Lin",
                role="AI 工程师",
                recipient_email="private@example.test",
            )
        )


def build_generator(
    session_factory,
    context: ToolContext,
    responses: list[AIMessage] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    resolver=None,
    model=None,
):
    model = model or ScriptedModel(responses or [])
    news_options = {"transport": transport}
    if resolver is not None:
        news_options["resolver"] = resolver
    news = NewsService(**news_options)
    runner = AgentRunner(
        model,
        create_default_registry(news_service=news),
        limits=AgentLimits(model_timeout_seconds=1, max_tool_rounds=6, task_timeout_seconds=5),
    )
    return BriefGenerationService(runner, session_factory), model


def task_context(tmp_path, run_id, source, repository) -> ToolContext:
    for directory in ("inputs", "history", "drafts"):
        (tmp_path / directory).mkdir(exist_ok=True)
    return ToolContext(
        run_id=run_id,
        workspace_root=tmp_path,
        news_sources=(source,),
        news_repository=repository,
    )


def test_partial_source_failure_is_saved_as_user_visible_coverage_warning(
    tmp_path,
    session_factory,
    rss_source,
    response_handler,
    public_resolver,
):
    ensure_user(session_factory)
    broken = rss_source.model_copy(
        update={"source_id": "broken-feed", "feed_url": "https://feeds.example.test/broken"}
    )
    context = task_context(tmp_path, "partial-sources", rss_source, None)
    from dataclasses import replace

    context = replace(context, news_sources=(rss_source, broken))

    def transport(request):
        return httpx.Response(503) if request.url.path == "/broken" else response_handler(request)

    generator, _ = build_generator(
        session_factory,
        context,
        [
            tool_call(
                "fetch_rss", {"source_ids": [rss_source.source_id, broken.source_id]}, "partial-rss"
            ),
            final_brief([article_id("/news/agent?id=1")]),
        ],
        transport=httpx.MockTransport(transport),
        resolver=public_resolver,
    )
    result = asyncio.run(generator.generate(preferences(), context, REPORT_DATE))
    assert result.run_status == "completed" and result.warnings == [
        "部分新闻来源读取失败，本期覆盖范围有限。"
    ]
    with session_factory() as session:
        saved = session.get(BriefRecord, result.id)
        assert saved.content_json["warnings"] == result.warnings


def test_model_decisions_drive_different_brief_traces_and_persist_evidence(
    tmp_path, session_factory, rss_source, news_repository, response_handler, public_resolver
) -> None:
    ensure_user(session_factory)
    news_repository.sync_sources((rss_source,))
    agent_item_id = article_id("/news/agent?id=1")
    research_item_id = article_id("/news/research?id=2")

    first_context = task_context(tmp_path, "run-agent-topic", rss_source, news_repository)
    first_generator, first_model = build_generator(
        session_factory,
        first_context,
        transport=httpx.MockTransport(response_handler),
        resolver=public_resolver,
        model=PreferenceAwareModel(),
    )
    first = asyncio.run(
        first_generator.generate(
            preferences(),
            first_context,
            REPORT_DATE,
            delivery_recipient="reader@example.org",
        )
    )

    second_context = task_context(tmp_path, "run-research-topic", rss_source, news_repository)
    second_generator, second_model = build_generator(
        session_factory,
        second_context,
        transport=httpx.MockTransport(response_handler),
        resolver=public_resolver,
        model=PreferenceAwareModel(),
    )
    second = asyncio.run(
        second_generator.generate(
            preferences(topics=["大模型与研究"], keywords=["Research"]),
            second_context,
            REPORT_DATE,
        )
    )

    assert first.run_status == second.run_status == "completed"
    assert [item.article_id for item in first.items] == [agent_item_id]
    assert [item.article_id for item in second.items] == [research_item_id]
    assert first.items[0].title == "Agent release"
    assert first.items[0].source_name == "Example AI Feed"
    assert first.items[0].published_at_raw == "Tue, 21 Nov 2023 12:30:00 GMT"
    assert first.items[0].source_excerpt == "An Agent release."
    assert _trace_names(session_factory, first.run_id) == ["fetch_rss"]
    assert _trace_names(session_factory, second.run_id) == ["fetch_rss", "search_news"]

    task_prompt = first_model.messages[0][-1].content
    second_task_prompt = second_model.messages[0][-1].content
    assert "Agent 与工具" in task_prompt and "AI 工程师" in task_prompt
    assert "大模型与研究" in second_task_prompt and "Research" in second_task_prompt
    assert "recipient_email" not in task_prompt and "private@example.test" not in task_prompt
    with session_factory() as session:
        run = session.get(TaskRunRecord, first.run_id)
        brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == first.run_id))
        article = session.scalar(
            select(NewsItemRecord).where(NewsItemRecord.article_id == agent_item_id)
        )
        first_call = session.scalar(
            select(ToolCallRecord).where(ToolCallRecord.run_id == first.run_id)
        )
        delivery = session.scalar(
            select(MailDeliveryRecord).where(MailDeliveryRecord.brief_id == brief.id)
        )
    assert run is not None and run.status == "completed" and run.finished_at is not None
    assert run.preferences_snapshot["keywords"] == ["Agent"]
    assert brief is not None and brief.content_json["item_count"] == 1
    assert article is not None and article.included_at is not None
    assert first_call is not None
    assert first_call.attempt == 1
    assert first_call.args_redacted == {"source_ids": "<list:1 items>"}
    assert "example-ai" not in json.dumps(first_call.args_redacted)
    assert delivery is not None
    assert delivery.status == "pending"
    assert delivery.recipient_snapshot == "reader@example.org"


def _trace_names(session_factory, run_id: str) -> list[str]:
    with session_factory() as session:
        calls = session.scalars(
            select(ToolCallRecord)
            .where(ToolCallRecord.run_id == run_id)
            .order_by(ToolCallRecord.iteration, ToolCallRecord.id)
        )
        return [call.tool_name for call in calls]


def test_empty_brief_requires_checked_rss_evidence_and_persists_empty_status(
    tmp_path, session_factory, rss_source, news_repository, public_resolver
) -> None:
    ensure_user(session_factory)
    news_repository.sync_sources((rss_source,))
    empty_feed = b"<rss version='2.0'><channel><title>Empty</title></channel></rss>"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=empty_feed))
    context = task_context(tmp_path, "run-empty-brief", rss_source, news_repository)
    generator, _model = build_generator(
        session_factory,
        context,
        [
            tool_call("fetch_rss", {"source_ids": [rss_source.source_id]}, "rss-empty"),
            final_brief([]),
        ],
        transport=transport,
        resolver=public_resolver,
    )

    result = asyncio.run(generator.generate(preferences(), context, REPORT_DATE))

    assert result.run_status == "empty"
    assert result.item_count == 0
    assert result.empty_reason == "今日暂无符合偏好的新闻。"
    with session_factory() as session:
        run = session.get(TaskRunRecord, context.run_id)
        brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == context.run_id))
    assert run is not None and run.status == "empty"
    assert brief is not None and brief.content_json["items"] == []


def test_empty_brief_without_fetch_evidence_is_a_failed_run(
    tmp_path, session_factory, rss_source, news_repository
) -> None:
    ensure_user(session_factory)
    news_repository.sync_sources((rss_source,))
    context = task_context(tmp_path, "run-empty-no-evidence", rss_source, news_repository)
    generator, _model = build_generator(session_factory, context, [final_brief([])])

    with pytest.raises(BriefGenerationError, match="empty_brief_without_news_evidence"):
        asyncio.run(generator.generate(preferences(), context, REPORT_DATE))

    with session_factory() as session:
        run = session.get(TaskRunRecord, context.run_id)
        brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == context.run_id))
    assert run is not None and run.status == "failed"
    assert run.error_code == "empty_brief_without_news_evidence"
    assert brief is None


def test_unknown_article_reference_and_excluded_keyword_never_save_briefs(
    tmp_path, session_factory, rss_source, news_repository, response_handler, public_resolver
) -> None:
    ensure_user(session_factory)
    news_repository.sync_sources((rss_source,))
    unknown_context = task_context(tmp_path, "run-unknown-article", rss_source, news_repository)
    hidden_candidate_id = "f" * 32
    unknown_context.news_candidates[hidden_candidate_id] = NewsArticle(
        article_id=hidden_candidate_id,
        url_hash="e" * 64,
        source_id=rss_source.source_id,
        source_name=rss_source.name,
        category=rss_source.category,
        title="Hidden from the model",
        summary="This candidate was loaded but never surfaced.",
        url="https://articles.example.test/hidden",
        canonical_url="https://articles.example.test/hidden",
        fetched_at_utc="2026-11-21T00:00:00+00:00",
    )
    unknown_generator, _ = build_generator(
        session_factory, unknown_context, [final_brief([hidden_candidate_id])]
    )
    with pytest.raises(BriefGenerationError, match="article_not_in_task_evidence"):
        asyncio.run(unknown_generator.generate(preferences(), unknown_context, REPORT_DATE))

    excluded_context = task_context(tmp_path, "run-excluded-article", rss_source, news_repository)
    excluded_generator, _ = build_generator(
        session_factory,
        excluded_context,
        [
            tool_call("fetch_rss", {"source_ids": [rss_source.source_id]}, "rss-excluded"),
            final_brief([article_id("/news/agent?id=1")]),
        ],
        transport=httpx.MockTransport(response_handler),
        resolver=public_resolver,
    )
    with pytest.raises(BriefGenerationError, match="excluded_keyword_match"):
        asyncio.run(
            excluded_generator.generate(
                preferences(excluded=["release"]), excluded_context, REPORT_DATE
            )
        )

    with session_factory() as session:
        briefs = list(session.scalars(select(BriefRecord)))
        excluded_run = session.get(TaskRunRecord, excluded_context.run_id)
    assert briefs == []
    assert excluded_run is not None and excluded_run.error_code == "excluded_keyword_match"


def test_missing_source_metadata_fails_without_exposing_model_generated_source_fields(
    tmp_path, session_factory, rss_source
) -> None:
    ensure_user(session_factory)
    context = task_context(tmp_path, "run-missing-source", rss_source, None)
    candidate_id = "a" * 32
    context.news_candidates[candidate_id] = NewsArticle(
        article_id=candidate_id,
        url_hash="b" * 64,
        source_id=rss_source.source_id,
        source_name="",
        category="AI",
        title="A real candidate",
        summary="Evidence from RSS.",
        url="https://articles.example.test/story",
        canonical_url="https://articles.example.test/story",
        fetched_at_utc="2026-11-21T00:00:00+00:00",
    )
    context.news_visible_article_ids.add(candidate_id)
    generator, _model = build_generator(session_factory, context, [final_brief([candidate_id])])

    with pytest.raises(BriefGenerationError, match="article_source_fields_missing"):
        asyncio.run(generator.generate(preferences(), context, REPORT_DATE))

    with session_factory() as session:
        run = session.get(TaskRunRecord, context.run_id)
    assert run is not None and run.error_code == "article_source_fields_missing"


def test_invalid_model_json_is_recorded_as_failed_without_saving_a_brief(
    tmp_path, session_factory, rss_source
) -> None:
    ensure_user(session_factory)
    context = task_context(tmp_path, "run-invalid-json", rss_source, None)
    generator, _model = build_generator(
        session_factory, context, [AIMessage(content="This is not JSON.")]
    )

    with pytest.raises(BriefGenerationError, match="brief_validation_failed"):
        asyncio.run(generator.generate(preferences(), context, REPORT_DATE))

    with session_factory() as session:
        run = session.get(TaskRunRecord, context.run_id)
        brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == context.run_id))
    assert run is not None and run.error_code == "brief_validation_failed"
    assert brief is None


def test_task_creation_distinguishes_missing_user_and_duplicate_idempotency_key(
    tmp_path, session_factory, rss_source
) -> None:
    missing_user_context = task_context(tmp_path, "run-no-user", rss_source, None)
    missing_user_generator, _ = build_generator(session_factory, missing_user_context, [])
    with pytest.raises(BriefGenerationError, match="task_user_not_found"):
        asyncio.run(
            missing_user_generator.generate(preferences(), missing_user_context, REPORT_DATE)
        )

    ensure_user(session_factory)
    first_context = task_context(tmp_path, "run-idempotent-first", rss_source, None)
    first_generator, _ = build_generator(session_factory, first_context, [final_brief([])])
    with pytest.raises(BriefGenerationError, match="empty_brief_without_news_evidence"):
        asyncio.run(
            first_generator.generate(
                preferences(),
                first_context,
                REPORT_DATE,
                idempotency_key="daily:1:2026-11-21",
            )
        )

    second_context = task_context(tmp_path, "run-idempotent-second", rss_source, None)
    second_generator, _ = build_generator(session_factory, second_context, [])
    with pytest.raises(BriefGenerationError, match="run_already_exists"):
        asyncio.run(
            second_generator.generate(
                preferences(),
                second_context,
                REPORT_DATE,
                idempotency_key="daily:1:2026-11-21",
            )
        )


def test_brief_and_news_inclusion_roll_back_together_on_persistence_failure(
    tmp_path,
    session_factory,
    rss_source,
    news_repository,
    response_handler,
    public_resolver,
    monkeypatch,
) -> None:
    ensure_user(session_factory)
    news_repository.sync_sources((rss_source,))
    context = task_context(tmp_path, "run-brief-rollback", rss_source, news_repository)

    def fail_after_mark(session, article_ids, _source_cursors):
        session.execute(
            update(NewsItemRecord)
            .where(NewsItemRecord.article_id.in_(article_ids))
            .values(included_at=utc_now())
        )
        raise SQLAlchemyError("simulated brief transaction failure")

    monkeypatch.setattr(NewsRepository, "mark_task_success", staticmethod(fail_after_mark))
    generator, _model = build_generator(
        session_factory,
        context,
        [
            tool_call("fetch_rss", {"source_ids": [rss_source.source_id]}, "rss-rollback"),
            final_brief([article_id("/news/agent?id=1")]),
        ],
        transport=httpx.MockTransport(response_handler),
        resolver=public_resolver,
    )

    with pytest.raises(BriefGenerationError, match="brief_persistence_failed"):
        asyncio.run(
            generator.generate(
                preferences(),
                context,
                REPORT_DATE,
                delivery_recipient="reader@example.org",
            )
        )

    with session_factory() as session:
        run = session.get(TaskRunRecord, context.run_id)
        brief = session.scalar(select(BriefRecord).where(BriefRecord.run_id == context.run_id))
        delivery = session.scalar(select(MailDeliveryRecord))
        article = session.scalar(
            select(NewsItemRecord).where(
                NewsItemRecord.article_id == article_id("/news/agent?id=1")
            )
        )
    assert run is not None and run.status == "failed"
    assert run.error_code == "brief_persistence_failed"
    assert brief is None
    assert delivery is None
    assert article is not None and article.included_at is None
