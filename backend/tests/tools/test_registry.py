import json

import pytest

from app.tools.registry import ToolDefinition, ToolRegistry, ToolResult
from app.tools.schemas import ListDirArguments

REQUIRED_TOOLS = {"list_dir", "read_file", "search_content", "write_file", "bash"}
NEWS_TOOLS = {"fetch_rss", "search_news", "fetch_article"}


def test_all_required_tools_are_registered_and_exposed_as_function_schemas(tool_registry) -> None:
    schemas = tool_registry.model_schemas()
    assert REQUIRED_TOOLS <= set(tool_registry.names())
    assert REQUIRED_TOOLS | NEWS_TOOLS <= {item["function"]["name"] for item in schemas}
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["description"]
        assert schema["function"]["parameters"]["type"] == "object"
        assert schema["function"]["parameters"]["additionalProperties"] is False
    schemas_by_name = {item["function"]["name"]: item["function"] for item in schemas}
    assert set(schemas_by_name["fetch_rss"]["parameters"]["properties"]) == {"source_ids"}
    assert set(schemas_by_name["fetch_article"]["parameters"]["properties"]) == {"article_id"}
    assert "only the RSS candidate" in schemas_by_name["search_news"]["description"]


def test_duplicate_tool_names_are_rejected() -> None:
    registry = ToolRegistry()
    tool = ToolDefinition("example", "Example.", ListDirArguments, lambda _args, _ctx: {})
    registry.register(tool)
    with pytest.raises(ValueError, match="duplicate_tool_name"):
        registry.register(tool)


def test_unknown_and_invalid_calls_return_stable_errors(tool_registry, tool_context) -> None:
    assert tool_registry.execute("missing", {}, tool_context).to_dict() == {
        "ok": False,
        "error": "unknown_tool",
    }
    assert tool_registry.execute("read_file", {"unexpected": True}, tool_context).to_dict() == {
        "ok": False,
        "error": "invalid_arguments",
    }
    assert (
        tool_registry.execute(
            "read_file", {"path": "inputs/news.md", "workspace_root": "C:/"}, tool_context
        ).error_code
        == "invalid_arguments"
    )


def test_tool_result_to_model_content_is_bounded_and_valid_json() -> None:
    result = ToolResult(ok=True, data={"text": "新闻报道。" * 20_000})
    content = result.to_model_content()
    assert len(content.encode("utf-8")) <= ToolResult.MAX_MODEL_CONTENT_BYTES
    assert json.loads(content)["data"]["truncated"] is True
