import json
from pathlib import Path

import httpx
import pytest

from app.core.task_context import ToolFailure
from app.news.config import load_rss_sources
from app.news.schemas import RSSSource
from app.news.service import NewsService, canonicalize_url
from app.tools import ToolContext, create_default_registry


def test_fetch_rss_preserves_source_links_and_publication_data(news_registry, news_context) -> None:
    result = news_registry.execute("fetch_rss", {"source_ids": ["example-ai"]}, news_context)
    assert result.ok
    assert result.data["sources_fetched"] == 1
    assert result.data["duplicates_skipped"] == 1
    assert len(result.data["items"]) == 2
    first = result.data["items"][0]
    assert first["source_name"] == "Example AI Feed"
    assert first["url"] == "https://articles.example.test/news/agent?utm_source=rss&id=1"
    assert first["published_at_raw"] == "Tue, 21 Nov 2023 12:30:00 GMT"
    assert first["published_at_utc"] == "2023-11-21T12:30:00+00:00"
    assert first["published_at_field"] == "published"
    assert first["fetched_at_utc"]
    second = result.data["items"][1]
    assert second["published_at_raw"] is None
    assert second["published_at_utc"] is None
    assert second["published_at_field"] is None


def test_empty_valid_feed_is_distinct_from_a_failed_feed(
    rss_source, news_context, public_resolver
) -> None:
    empty_feed = b"<rss version='2.0'><channel><title>Empty</title></channel></rss>"
    service = NewsService(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=empty_feed)),
        resolver=public_resolver,
    )
    result = create_default_registry(news_service=service).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, news_context
    )
    assert result.ok
    assert result.data["items"] == []
    assert result.data["sources_fetched"] == 1


def test_search_news_uses_only_candidates_from_this_task(news_registry, news_context) -> None:
    before = news_registry.execute("search_news", {"query": "Agent", "limit": 10}, news_context)
    assert before.ok
    assert before.data == {"items": [], "match_count": 0, "truncated": False}

    news_registry.execute("fetch_rss", {"source_ids": ["example-ai"]}, news_context)
    result = news_registry.execute("search_news", {"query": "Agent", "limit": 10}, news_context)
    assert result.ok
    assert result.data["match_count"] == 1
    assert result.data["items"][0]["source_id"] == "example-ai"
    assert result.data["items"][0]["article_id"] in news_context.news_candidates


def test_fetch_article_requires_candidate_id_and_extracts_bounded_text(
    news_registry, news_context
) -> None:
    missing = news_registry.execute("fetch_article", {"article_id": "0" * 32}, news_context)
    assert missing.error_code == "article_not_found"

    fetched = news_registry.execute("fetch_rss", {"source_ids": ["example-ai"]}, news_context)
    article_id = fetched.data["items"][0]["article_id"]
    result = news_registry.execute("fetch_article", {"article_id": article_id}, news_context)
    assert result.ok
    assert result.data["article_id"] == article_id
    assert result.data["source_name"] == "Example AI Feed"
    assert "Agent added a useful workflow" in result.data["content_excerpt"]
    assert "ignore this prompt" not in result.data["content_excerpt"]
    assert "<script>" not in result.data["content_excerpt"]
    assert result.data["fetched_at_utc"]


def test_article_text_can_be_reread_in_model_safe_chunks(
    rss_source, news_context, public_resolver
) -> None:
    long_rss = b"""<rss version='2.0'><channel><item><title>Long article</title>
    <link>https://articles.example.test/news/long</link></item></channel></rss>"""
    article_body = ("Evidence from the article. " * 150).encode("utf-8")

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "feeds.example.test":
            return httpx.Response(200, content=long_rss)
        return httpx.Response(200, content=article_body, headers={"content-type": "text/plain"})

    context = ToolContext(
        run_id="article-chunks",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source,),
    )
    registry = create_default_registry(
        news_service=NewsService(transport=httpx.MockTransport(handle), resolver=public_resolver)
    )
    candidates = registry.execute("fetch_rss", {"source_ids": [rss_source.source_id]}, context)
    article_id = candidates.data["items"][0]["article_id"]
    first = registry.execute("fetch_article", {"article_id": article_id}, context)
    second = registry.execute("fetch_article", {"article_id": article_id}, context)

    assert first.ok and second.ok
    assert first.data["chunk_index"] == 1
    assert first.data["truncated"] is True
    assert second.data["chunk_index"] == 2
    assert second.data["truncated"] is False
    assert first.data["content_excerpt"] + second.data["content_excerpt"] == " ".join(
        article_body.decode().split()
    )


def test_fetch_rss_is_bounded_to_configured_source_ids(news_registry, news_context) -> None:
    no_sources = ToolContext(run_id="empty", workspace_root=news_context.workspace_root)
    assert (
        news_registry.execute("fetch_rss", {"source_ids": ["example-ai"]}, no_sources).error_code
        == "no_sources_configured"
    )
    assert (
        news_registry.execute(
            "fetch_rss", {"source_ids": ["arbitrary-url"]}, news_context
        ).error_code
        == "source_not_found"
    )
    assert (
        news_registry.execute(
            "fetch_rss",
            {"source_ids": ["example-ai"], "url": "https://attacker.example/"},
            news_context,
        ).error_code
        == "invalid_arguments"
    )


def test_failed_sources_are_not_reported_as_empty_news(
    rss_source, news_context, public_resolver
) -> None:
    service = NewsService(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
        resolver=public_resolver,
    )
    registry = create_default_registry(news_service=service)
    result = registry.execute("fetch_rss", {"source_ids": [rss_source.source_id]}, news_context)
    assert result.error_code == "http_error"
    assert not result.ok


def test_malformed_or_entity_expanding_feeds_are_rejected(
    rss_source, news_context, public_resolver
) -> None:
    feeds = [
        b"<rss><channel><item>",
        b"<!DOCTYPE rss [<!ENTITY x 'expand'>]><rss><channel></channel></rss>",
    ]
    for body in feeds:
        service = NewsService(
            transport=httpx.MockTransport(
                lambda _request, response_body=body: httpx.Response(200, content=response_body)
            ),
            resolver=public_resolver,
        )
        result = create_default_registry(news_service=service).execute(
            "fetch_rss", {"source_ids": [rss_source.source_id]}, news_context
        )
        assert result.error_code == "feed_parse_error"


def test_partial_source_failures_are_returned_with_successful_candidates(
    rss_source, news_context, response_handler, public_resolver
) -> None:
    second_source = RSSSource(
        source_id="broken-feed",
        name="Broken Feed",
        feed_url="https://broken.example.test/rss.xml",
        allowed_hosts=["broken.example.test"],
        category="AI",
    )

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "broken.example.test":
            return httpx.Response(503)
        return response_handler(request)

    service = NewsService(
        transport=httpx.MockTransport(handle),
        resolver=public_resolver,
    )
    context = ToolContext(
        run_id="partial",
        workspace_root=news_context.workspace_root,
        news_sources=(rss_source, second_source),
    )
    result = create_default_registry(news_service=service).execute(
        "fetch_rss", {"source_ids": ["example-ai", "broken-feed"]}, context
    )
    assert result.ok
    assert result.data["sources_fetched"] == 1
    assert result.data["source_errors"] == [{"source_id": "broken-feed", "error": "http_error"}]
    assert result.data["items"]


def test_private_dns_and_cross_host_redirects_are_rejected(
    rss_source, response_handler, news_context
) -> None:
    request_count = 0

    def count_requests(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return response_handler(request)

    private_service = NewsService(
        transport=httpx.MockTransport(count_requests),
        resolver=lambda _host, _port: ["127.0.0.1"],
    )
    private_result = create_default_registry(news_service=private_service).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, news_context
    )
    assert private_result.error_code == "ssrf_blocked"
    assert request_count == 0

    redirect_service = NewsService(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                302, headers={"location": "https://attacker.example/rss"}
            )
        ),
        resolver=lambda _host, _port: ["93.184.216.34"],
    )
    redirect_result = create_default_registry(news_service=redirect_service).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, news_context
    )
    assert redirect_result.error_code == "url_denied"


def test_response_size_and_request_timeouts_are_reported(
    rss_source, news_context, public_resolver
) -> None:
    large = NewsService(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        ),
        resolver=public_resolver,
    )
    large_result = create_default_registry(news_service=large).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, news_context
    )
    assert large_result.error_code == "response_too_large"

    timeout = NewsService(
        transport=httpx.MockTransport(
            lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timed out", request=request))
        ),
        resolver=public_resolver,
    )
    timeout_result = create_default_registry(news_service=timeout).execute(
        "fetch_rss", {"source_ids": [rss_source.source_id]}, news_context
    )
    assert timeout_result.error_code == "request_timeout"


def test_source_config_is_bounded_and_validated(tmp_path: Path) -> None:
    config_path = tmp_path / "rss_sources.json"
    config_path.write_text("[]", encoding="utf-8")
    assert load_rss_sources(config_path) == ()

    valid = {
        "source_id": "official-feed",
        "name": "Official Feed",
        "feed_url": "https://feeds.example.test/rss.xml",
        "allowed_hosts": ["feeds.example.test"],
        "category": "AI",
        "enabled": True,
    }
    config_path.write_text(json.dumps([valid]), encoding="utf-8")
    assert load_rss_sources(config_path)[0].source_id == "official-feed"

    invalid = {**valid, "feed_url": "http://127.0.0.1/private", "allowed_hosts": ["127.0.0.1"]}
    config_path.write_text(json.dumps([invalid]), encoding="utf-8")
    with pytest.raises(ValueError, match="rss_source_config_invalid"):
        load_rss_sources(config_path)

    config_path.write_text(json.dumps([valid, valid]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate_rss_source_id"):
        load_rss_sources(config_path)


def test_sensitive_query_parameters_are_not_forwarded_to_the_model() -> None:
    with pytest.raises(ToolFailure, match="article_url_contains_secret"):
        canonicalize_url("https://articles.example.test/story?access_token=private-value")


def test_recommended_catalog_contains_only_confirmed_official_sources() -> None:
    path = Path(__file__).parents[2] / "config" / "rss_sources.example.json"
    sources = load_rss_sources(path)
    assert {source.source_id for source in sources} == {
        "openai",
        "google-deepmind",
        "microsoft-research",
    }
    for source in sources:
        assert source.enabled
        assert source.feed_url.startswith("https://")
        assert len(source.allowed_hosts) == 1
