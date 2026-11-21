import asyncio
import os

import pytest

from app.agent import AgentLimits, AgentRunner
from app.agent.model import create_chat_model
from app.core.config import Settings
from app.tools import ToolContext, create_default_registry


@pytest.mark.real_llm
def test_openai_compatible_model_completes_a_real_tool_call(tmp_path) -> None:
    if os.getenv("RUN_REAL_LLM_TESTS") != "1":
        pytest.skip("set RUN_REAL_LLM_TESTS=1 to opt in to a real model request")

    settings = Settings()
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        pytest.skip("LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL are required")
    if (
        settings.llm_api_key.get_secret_value() == "replace_me"
        or settings.llm_model == "replace_with_model_id"
        or "example.com" in settings.llm_base_url
    ):
        pytest.skip("replace the example LLM settings before opting in")

    (tmp_path / "inputs").mkdir()
    (tmp_path / "history").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / "inputs" / "real-check.txt").write_text("real tool result", encoding="utf-8")
    runner = AgentRunner(
        model=create_chat_model(settings),
        registry=create_default_registry(),
        limits=AgentLimits(
            model_timeout_seconds=settings.agent_model_timeout_seconds,
            max_tool_rounds=2,
            task_timeout_seconds=120,
        ),
    )
    result = asyncio.run(
        runner.run(
            "Call list_dir once with path 'inputs', then report the returned file names. Do not call any other tool.",
            ToolContext(run_id="real-model-check", workspace_root=tmp_path),
        )
    )

    assert result.status == "completed", result.termination_reason
    assert any(
        event.kind == "tool_execution"
        and event.tool_name == "list_dir"
        and event.status == "succeeded"
        for event in result.events
    )
