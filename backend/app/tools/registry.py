import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from app.news.service import NewsService
from app.tools.commands import run_restricted_command
from app.tools.context import ToolContext, ToolFailure
from app.tools.filesystem import list_directory, read_text_file, search_text, write_draft
from app.tools.schemas import (
    BashArguments,
    FetchArticleArguments,
    FetchRSSArguments,
    ListDirArguments,
    ReadFileArguments,
    SearchContentArguments,
    SearchNewsArguments,
    ToolArguments,
    WriteFileArguments,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] | None = None
    error_code: str | None = None
    MAX_MODEL_CONTENT_BYTES = 12 * 1024

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "data": self.data or {}}
        return {"ok": False, "error": self.error_code or "tool_failed"}

    def to_model_content(self) -> str:
        content = json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))
        if len(content.encode("utf-8")) <= self.MAX_MODEL_CONTENT_BYTES:
            return content
        preview = content[:2500]
        while preview:
            bounded = json.dumps(
                {"ok": self.ok, "data": {"truncated": True, "preview": preview}},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            if len(bounded.encode("utf-8")) <= self.MAX_MODEL_CONTENT_BYTES:
                return bounded
            preview = preview[: len(preview) * 3 // 4]
        return '{"ok":false,"error":"tool_result_too_large"}'


ToolHandler = Callable[[BaseModel, ToolContext], dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[ToolArguments]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ValueError("duplicate_tool_name")
        self._tools[tool.name] = tool

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def model_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.arguments.model_json_schema(),
                },
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, raw_arguments: Any, context: ToolContext) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error_code="unknown_tool")
        try:
            arguments = tool.arguments.model_validate(raw_arguments)
        except ValidationError:
            return ToolResult(ok=False, error_code="invalid_arguments")
        try:
            return ToolResult(ok=True, data=tool.handler(arguments, context))
        except ToolFailure as error:
            return ToolResult(ok=False, error_code=error.code)
        except OSError:
            logger.warning("tool execution failed (%s)", name)
            return ToolResult(ok=False, error_code="io_error")
        except Exception as error:  # noqa: BLE001 - tool failures must never escape the executor
            logger.error("tool execution failed (%s, %s)", name, type(error).__name__)
            return ToolResult(ok=False, error_code="tool_failed")


def create_default_registry(news_service: NewsService | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    news = news_service or NewsService()
    registry.register(
        ToolDefinition(
            name="list_dir",
            description="List visible entries in the current task workspace.",
            arguments=ListDirArguments,
            handler=lambda args, context: list_directory(args.path, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="read_file",
            description="Read a bounded UTF-8 material file from inputs/ or history/.",
            arguments=ReadFileArguments,
            handler=lambda args, context: read_text_file(args.path, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="search_content",
            description="Search local task materials in inputs/ or history/; does not access the internet.",
            arguments=SearchContentArguments,
            handler=lambda args, context: search_text(args.keyword, args.dir, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            description="Atomically create or replace a bounded draft file inside drafts/.",
            arguments=WriteFileArguments,
            handler=lambda args, context: write_draft(args.path, args.content, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="bash",
            description="Run only python -m json.tool on a bounded inputs/ or history/ JSON material. Arbitrary shell commands, flags and programs are denied.",
            arguments=BashArguments,
            handler=lambda args, context: run_restricted_command(args.command, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="fetch_rss",
            description="Fetch entries from enabled, preconfigured RSS source IDs; the caller cannot provide feed URLs.",
            arguments=FetchRSSArguments,
            handler=lambda args, context: news.fetch_rss_tool(args.source_ids, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="search_news",
            description="Search only the RSS candidate items already fetched in this task; does not access the internet.",
            arguments=SearchNewsArguments,
            handler=lambda args, context: news.search_news_tool(args.query, args.limit, context),
        )
    )
    registry.register(
        ToolDefinition(
            name="fetch_article",
            description="Fetch readable text for an article ID returned by this task's RSS tools; arbitrary URLs are not accepted.",
            arguments=FetchArticleArguments,
            handler=lambda args, context: news.fetch_article_tool(args.article_id, context),
        )
    )
    return registry
