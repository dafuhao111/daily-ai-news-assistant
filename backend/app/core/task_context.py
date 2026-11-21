from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.news.schemas import NewsArticle, RSSSource


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    workspace_root: Path
    news_sources: tuple["RSSSource", ...] = ()
    news_candidates: dict[str, "NewsArticle"] = field(default_factory=dict, compare=False)
    news_visible_article_ids: set[str] = field(default_factory=set, compare=False)
    news_source_outcomes: dict[str, str] = field(default_factory=dict, compare=False)
    article_offsets: dict[str, int] = field(default_factory=dict, compare=False)
    news_repository: Any | None = field(default=None, compare=False, repr=False)


class ToolFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
