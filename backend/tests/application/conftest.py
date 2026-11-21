import httpx
import pytest

from app.news.repository import NewsRepository
from app.news.schemas import RSSSource


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
                200,
                content=b"""<rss version='2.0'><channel><title>Example AI Feed</title>
                <item><title>Agent release</title><description>An Agent release.</description>
                <link>https://articles.example.test/news/agent?utm_source=rss&amp;id=1</link>
                <pubDate>Tue, 21 Nov 2023 12:30:00 GMT</pubDate></item>
                <item><title>Research note</title><description>Research summary.</description>
                <link>https://articles.example.test/news/research?id=2</link></item>
                </channel></rss>""",
                headers={"content-type": "application/rss+xml"},
            )
        return httpx.Response(404)

    return handle


@pytest.fixture
def news_repository(session_factory) -> NewsRepository:
    return NewsRepository(session_factory)
