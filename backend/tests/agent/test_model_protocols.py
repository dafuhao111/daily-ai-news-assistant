import asyncio
import json

import httpx
import pytest
from langchain_core.messages import ToolMessage

from app.agent.model import create_chat_model
from app.core.config import Settings
from app.tools import create_default_registry


def test_default_model_clients_are_task_owned_and_never_shared_across_event_loops():
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from app.agent import AgentRunner
    from app.tools import ToolContext

    settings = Settings(
        _env_file=None,
        llm_base_url="https://gateway.example/v1",
        llm_api_key="test-placeholder",
        llm_model="test-model",
    )
    first = create_chat_model(settings)
    second = create_chat_model(settings)
    assert first.http_async_client is not second.http_async_client
    assert first._daily_owned_http_client is first.http_async_client
    # Resource guard prevents a network call; both distinct event loops still
    # close their own client through the actual runner lifecycle.
    from app.agent.runner import AgentLimits

    with TemporaryDirectory() as path:
        for index, model in enumerate((first, second)):
            result = asyncio.run(
                AgentRunner(
                    model, create_default_registry(), limits=AgentLimits(max_model_input_bytes=1024)
                ).run(
                    "Inspect task", ToolContext(run_id=f"loop-{index}", workspace_root=Path(path))
                )
            )
            assert result.termination_reason == "input_limit"
            assert model.http_async_client.is_closed


@pytest.mark.parametrize("protocol", ["chat_completions", "responses"])
def test_configured_protocol_returns_tool_calls_and_accepts_tool_results(
    protocol, session_factory
) -> None:
    from app.application.budget import TokenBudgetService

    ledger = TokenBudgetService(session_factory)
    ledger.initialize(1_000_000)
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        first = len(requests) == 1
        if protocol == "responses":
            output = (
                [
                    {
                        "type": "function_call",
                        "id": "fc_test",
                        "call_id": "call_test",
                        "name": "list_dir",
                        "arguments": '{"path":"inputs"}',
                    }
                ]
                if first
                else [
                    {
                        "type": "message",
                        "id": "msg_test",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": "Found the file.", "annotations": []}
                        ],
                    }
                ]
            )
            return httpx.Response(
                200,
                json={
                    "id": f"resp_{len(requests)}",
                    "object": "response",
                    "created_at": 1,
                    "model": "test-model",
                    "status": "completed",
                    "output": output,
                    "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                },
            )
        message = (
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_test",
                        "type": "function",
                        "function": {"name": "list_dir", "arguments": '{"path":"inputs"}'},
                    }
                ],
            }
            if first
            else {"role": "assistant", "content": "Found the file."}
        )
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl_{len(requests)}",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if first else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            },
        )

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model = create_chat_model(
                Settings(
                    _env_file=None,
                    llm_base_url="https://gateway.example/v1",
                    llm_api_key="test-placeholder",
                    llm_model="test-model",
                    llm_api_protocol=protocol,
                    llm_max_output_tokens=512,
                ),
                http_async_client=client,
                budget_service=ledger,
            ).bind_tools(create_default_registry().model_schemas(), tool_choice="auto")
            messages = [("human", "Inspect the inputs directory.")]
            first = await model.ainvoke(messages)
            assert first.tool_calls[0]["name"] == "list_dir"
            assert first.tool_calls[0]["args"] == {"path": "inputs"}
            final = await model.ainvoke(
                [
                    *messages,
                    first,
                    ToolMessage(
                        content='{"ok":true,"data":{"files":["news.txt"]}}',
                        tool_call_id="call_test",
                    ),
                ]
            )
            assert final.text == "Found the file."

    asyncio.run(exercise())
    expected_path = "/v1/responses" if protocol == "responses" else "/v1/chat/completions"
    assert [path for path, _payload in requests] == [expected_path, expected_path]
    for _path, payload in requests:
        assert payload["store"] is False
        limit = "max_output_tokens" if protocol == "responses" else "max_completion_tokens"
        assert payload[limit] == 512
        assert len(payload["tools"]) == 8
    if protocol == "responses":
        outputs = [x for x in requests[1][1]["input"] if x["type"] == "function_call_output"]
        assert outputs[0]["call_id"] == "call_test"
    else:
        outputs = [x for x in requests[1][1]["messages"] if x["role"] == "tool"]
        assert outputs[0]["tool_call_id"] == "call_test"
