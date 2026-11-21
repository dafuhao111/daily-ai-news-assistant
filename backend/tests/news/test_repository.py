import httpx
import pytest
from sqlalchemy import select

from app.models.news import NewsItemRecord, RSSSourceRecord
from app.news.repository import NewsRepository
from app.news.service import NewsService
from app.tools import ToolContext, create_default_registry


def test_news_repository_deduplicates_across_runs_and_keeps_unincluded_items(
    rss_source,
    news_context,
    news_repository: NewsRepository,
    response_handler,
    public_resolver,
    session_factory,
) -> None:
    news_repository.sync_sources((rss_source,))
    service = NewsService(transport=httpx.MockTransport(response_handler), resolver=public_resolver)
    first_context = ToolContext(
        run_id="first",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source,),
        news_repository=news_repository,
    )
    registry = create_default_registry(news_service=service)
    first = registry.execute("fetch_rss", {"source_ids": [rss_source.source_id]}, first_context)
    assert first.ok
    first_article_ids = [item["article_id"] for item in first.data["items"]]
    assert len(first_article_ids) == 2

    retry_context = ToolContext(
        run_id="retry",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source,),
        news_repository=news_repository,
    )
    failed_service = NewsService(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
        resolver=public_resolver,
    )
    recovered = create_default_registry(news_service=failed_service).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, retry_context
    )
    assert recovered.ok
    assert recovered.data["sources_fetched"] == 0
    assert recovered.data["source_errors"] == [
        {"source_id": rss_source.source_id, "error": "http_error"}
    ]
    assert {item["article_id"] for item in recovered.data["items"]} == set(first_article_ids)

    with session_factory.begin() as session:
        NewsRepository.mark_task_success(
            session, [first_article_ids[0]], {rss_source.source_id: "first-successful-item"}
        )
    next_context = ToolContext(
        run_id="next",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source,),
        news_repository=news_repository,
    )
    next_result = create_default_registry(news_service=service).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, next_context
    )
    assert next_result.ok
    assert first_article_ids[0] not in {item["article_id"] for item in next_result.data["items"]}
    assert first_article_ids[1] in {item["article_id"] for item in next_result.data["items"]}
    assert next_result.data["duplicates_skipped"] == 2


def test_repository_syncs_source_status_and_updates_article_content(
    rss_source,
    news_context,
    news_repository: NewsRepository,
    response_handler,
    public_resolver,
    session_factory,
) -> None:
    news_repository.sync_sources((rss_source,))
    context = ToolContext(
        run_id="persist",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source,),
        news_repository=news_repository,
    )
    registry = create_default_registry(
        news_service=NewsService(
            transport=httpx.MockTransport(response_handler), resolver=public_resolver
        )
    )
    result = registry.execute("fetch_rss", {"source_ids": [rss_source.source_id]}, context)
    article_id = result.data["items"][0]["article_id"]
    registry.execute("fetch_article", {"article_id": article_id}, context)
    with session_factory.begin() as session:
        NewsRepository.mark_task_success(
            session, [article_id], {rss_source.source_id: "cursor-from-successful-task"}
        )

    with session_factory() as session:
        source = session.get(RSSSourceRecord, rss_source.source_id)
        article = session.scalar(
            select(NewsItemRecord).where(NewsItemRecord.article_id == article_id)
        )
    assert source.last_fetch_at is not None
    assert source.last_error_code is None
    assert source.last_successful_cursor == "cursor-from-successful-task"
    assert article is not None
    assert "Agent added a useful workflow" in article.content_excerpt
    assert article.url_hash[:32] == article.article_id


def test_successful_brief_markers_share_the_callers_transaction(
    rss_source,
    news_context,
    news_repository: NewsRepository,
    response_handler,
    public_resolver,
    session_factory,
) -> None:
    news_repository.sync_sources((rss_source,))
    context = ToolContext(
        run_id="transaction-check",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source,),
        news_repository=news_repository,
    )
    result = create_default_registry(
        news_service=NewsService(
            transport=httpx.MockTransport(response_handler), resolver=public_resolver
        )
    ).execute("fetch_rss", {"source_ids": [rss_source.source_id]}, context)
    article_id = result.data["items"][0]["article_id"]

    with pytest.raises(RuntimeError, match="rollback"), session_factory.begin() as session:
        NewsRepository.mark_task_success(session, [article_id], {rss_source.source_id: "cursor-1"})
        raise RuntimeError("rollback")

    with session_factory() as session:
        article = session.scalar(
            select(NewsItemRecord).where(NewsItemRecord.article_id == article_id)
        )
        source = session.get(RSSSourceRecord, rss_source.source_id)
    assert article.included_at is None
    assert source.last_successful_cursor is None

    with session_factory.begin() as session:
        NewsRepository.mark_task_success(session, [article_id], {rss_source.source_id: "cursor-1"})
    with session_factory() as session:
        article = session.scalar(
            select(NewsItemRecord).where(NewsItemRecord.article_id == article_id)
        )
        source = session.get(RSSSourceRecord, rss_source.source_id)
    assert article.included_at is not None
    assert source.last_successful_cursor == "cursor-1"
