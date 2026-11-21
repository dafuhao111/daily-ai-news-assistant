from pathlib import Path

from app.core.config import Settings
from app.core.task_context import ToolContext
from app.news.config import load_rss_sources
from app.news.repository import NewsRepository


def create_tool_context(
    run_id: str,
    workspace_root: Path,
    settings: Settings,
    news_repository: NewsRepository | None = None,
) -> ToolContext:
    sources = load_rss_sources(settings.rss_sources_file)
    if news_repository is not None:
        news_repository.sync_sources(sources)
    return ToolContext(
        run_id=run_id,
        workspace_root=workspace_root,
        news_sources=sources,
        news_repository=news_repository,
    )
