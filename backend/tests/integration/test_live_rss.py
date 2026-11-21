import os

import pytest

from app.core.config import Settings
from app.news.context import create_tool_context
from app.tools import create_default_registry


@pytest.mark.live_rss
def test_configured_public_rss_source_is_reachable(tmp_path) -> None:
    if os.getenv("RUN_LIVE_RSS_TESTS") != "1":
        pytest.skip("set RUN_LIVE_RSS_TESTS=1 to opt in to a live RSS request")

    settings = Settings()
    context = create_tool_context("live-rss-check", tmp_path, settings)
    sources = [source for source in context.news_sources if source.enabled]
    if not sources:
        pytest.skip("configure at least one enabled public RSS source first")

    result = create_default_registry().execute(
        "fetch_rss", {"source_ids": [sources[0].source_id]}, context
    )
    assert result.ok, result.error_code
    assert result.data["sources_fetched"] == 1
