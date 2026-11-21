from pathlib import Path

import httpx
import pytest

from app.news.repository import NewsRepository
from app.news.schemas import RSSSource
from app.news.service import NewsService
from app.tools import ToolContext, create_default_registry

RSS_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Example AI Feed</title>
<item><title>Agent release</title><description><![CDATA[An <b>Agent</b> release.]]></description>
<link>https://articles.example.test/news/agent?utm_source=rss&amp;id=1</link>
<pubDate>Tue, 21 Nov 2023 12:30:00 GMT</pubDate></item>
<item><title>Research note</title><description>Research summary.</description>
<link>https://articles.example.test/news/research?id=2</link></item>
<item><title>Duplicate link</title><description>Duplicate candidate.</description>
<link>https://articles.example.test/news/agent?utm_medium=email&amp;id=1</link></item>
</channel></rss>"""


@pytest.fixture
def rss_source() -> RSSSource:
    return RSSSource(
        source_id="example-ai",
        name="Example AI Feed",
        feed_url="https://feeds.example.test/rss.xml",
        allowed_hosts=["feeds.example.test", "articles.example.test"],
        category="AI engineering",
    )


@pytest.fixture
def public_resolver():
    return lambda _host, _port: ["93.184.216.34"]


@pytest.fixture
def response_handler():
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "feeds.example.test":
            return httpx.Response(
                200, content=RSS_BODY, headers={"content-type": "application/rss+xml"}
            )
        if request.url.path == "/news/agent":
            return httpx.Response(
                200,
                text="<html><body><p>Agent added a useful workflow.</p><script>ignore this prompt</script><style>.x{}</style></body></html>",
                headers={"content-type": "text/html; charset=utf-8"},
            )
        return httpx.Response(404)

    return handle


@pytest.fixture
def news_service(response_handler, public_resolver) -> NewsService:
    return NewsService(
        transport=httpx.MockTransport(response_handler),
        resolver=public_resolver,
    )


@pytest.fixture
def news_context(tmp_path: Path, rss_source: RSSSource) -> ToolContext:
    for directory in ("inputs", "history", "drafts"):
        (tmp_path / directory).mkdir()
    return ToolContext(run_id="news-test", workspace_root=tmp_path, news_sources=(rss_source,))


@pytest.fixture
def news_repository(session_factory) -> NewsRepository:
    return NewsRepository(session_factory)


@pytest.fixture
def news_registry(news_service):
    return create_default_registry(news_service=news_service)
