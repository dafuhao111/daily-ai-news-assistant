import asyncio
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage

from app.agent.runner import AgentLimits, AgentRunner
from app.tools import ToolContext, create_default_registry


class ScriptedModel:
    def __init__(self, responses: list[AIMessage | Exception], delay: float = 0) -> None:
        self.responses = list(responses)
        self.delay = delay
        self.schemas: list[dict[str, Any]] = []
        self.observed_messages: list[list[BaseMessage]] = []

    def bind_tools(self, tools: list[dict[str, Any]], **_kwargs: Any) -> "ScriptedModel":
        self.schemas = tools
        return self

    async def ainvoke(self, messages: list[BaseMessage]) -> AIMessage:
        self.observed_messages.append(list(messages))
        if self.delay:
            await asyncio.sleep(self.delay)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "inputs").mkdir()
    (tmp_path / "history").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "inputs" / "news.md").write_text(
        "Agent research\nA second line about RSS feeds.\n", encoding="utf-8"
    )
    (tmp_path / "history" / "previous.json").write_text(
        '{"title": "Older Agent report"}', encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def agent_context(workspace) -> ToolContext:
    return ToolContext(run_id="agent-test", workspace_root=workspace)


@pytest.fixture
def make_runner():
    def make(responses, *, limits=None, delay=0):
        model = ScriptedModel(responses, delay=delay)
        runner = AgentRunner(model, create_default_registry(), limits=limits)
        return runner, model

    return make


@pytest.fixture
def default_limits() -> AgentLimits:
    return AgentLimits(model_timeout_seconds=1, max_tool_rounds=8, task_timeout_seconds=2)
