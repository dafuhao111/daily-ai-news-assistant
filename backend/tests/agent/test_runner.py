import asyncio
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from app.agent import create_agent
from app.agent.model import ModelNotConfiguredError
from app.agent.runner import AgentLimits


def tool_call(name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}],
    )


def run_agent(runner, task, context):
    return asyncio.run(runner.run(task, context))


def execution_names(result) -> list[str | None]:
    return [event.tool_name for event in result.events if event.kind == "tool_execution"]


def test_different_model_tool_calls_produce_different_traces(make_runner, agent_context) -> None:
    search_runner, search_model = make_runner(
        [
            tool_call("search_content", {"keyword": "Agent", "dir": "inputs"}, "search-1"),
            AIMessage(content="The material contains an Agent item."),
        ]
    )
    read_runner, read_model = make_runner(
        [
            tool_call("read_file", {"path": "inputs/news.md"}, "read-1"),
            tool_call("list_dir", {"path": "history"}, "list-2"),
            AIMessage(content="I read the material and checked history."),
        ]
    )

    search_result = run_agent(search_runner, "Find Agent references.", agent_context)
    read_result = run_agent(read_runner, "Read the material and inspect history.", agent_context)

    assert search_result.status == read_result.status == "completed"
    assert execution_names(search_result) == ["search_content"]
    assert execution_names(read_result) == ["read_file", "list_dir"]
    assert execution_names(search_result) != execution_names(read_result)
    assert {item["function"]["name"] for item in search_model.schemas} == {
        "list_dir",
        "read_file",
        "search_content",
        "write_file",
        "bash",
    }
    assert {item["function"]["name"] for item in read_model.schemas} == {
        "list_dir",
        "read_file",
        "search_content",
        "write_file",
        "bash",
    }


def test_model_can_repeat_a_tool_and_decide_when_to_stop(make_runner, agent_context) -> None:
    runner, model = make_runner(
        [
            tool_call("list_dir", {"path": "inputs"}, "list-inputs"),
            tool_call("list_dir", {"path": "history"}, "list-history"),
            AIMessage(content="I checked both requested directories."),
        ]
    )
    result = run_agent(runner, "Inspect both directories.", agent_context)
    tool_results = [
        message for message in model.observed_messages[2] if isinstance(message, ToolMessage)
    ]
    assert result.status == "completed"
    assert execution_names(result) == ["list_dir", "list_dir"]
    assert [message.tool_call_id for message in tool_results] == ["list-inputs", "list-history"]


def test_real_chat_model_adapter_binds_all_registered_function_schemas() -> None:
    from app.core.config import Settings

    runner = create_agent(
        Settings(
            llm_api_key="dummy-test-key",
            llm_base_url="https://proxy.example/v1",
            llm_model="model-id-for-binding-test",
        )
    )
    assert runner.model.kwargs["tool_choice"] == "auto"
    assert {tool["function"]["name"] for tool in runner.model.kwargs["tools"]} == {
        "list_dir",
        "read_file",
        "search_content",
        "write_file",
        "bash",
    }


def test_tool_result_is_returned_with_matching_call_id(make_runner, agent_context) -> None:
    runner, model = make_runner(
        [
            tool_call("read_file", {"path": "inputs/news.md"}, "read-material-1"),
            AIMessage(content="The material discusses Agent research."),
        ]
    )

    result = run_agent(runner, "Read the file.", agent_context)

    assert result.status == "completed"
    returned = [
        message for message in model.observed_messages[1] if isinstance(message, ToolMessage)
    ]
    assert len(returned) == 1
    assert returned[0].tool_call_id == "read-material-1"
    assert json.loads(returned[0].content)["data"]["content"].startswith("Agent research")


def test_unknown_tool_and_invalid_arguments_return_errors_for_model(
    make_runner, agent_context
) -> None:
    runner, model = make_runner(
        [
            tool_call("not_registered", {}, "unknown-1"),
            AIMessage(content="The requested tool was unavailable, so I stopped."),
        ]
    )
    result = run_agent(runner, "Try a tool.", agent_context)
    returned = [
        message for message in model.observed_messages[1] if isinstance(message, ToolMessage)
    ]
    assert result.status == "completed"
    assert json.loads(returned[0].content) == {"ok": False, "error": "unknown_tool"}

    invalid_runner, invalid_model = make_runner(
        [
            tool_call("read_file", {"path": "inputs/news.md", "extra": "ignored?"}, "bad-args"),
            AIMessage(content="The arguments were invalid."),
        ]
    )
    invalid_result = run_agent(invalid_runner, "Read the file.", agent_context)
    invalid_returned = [
        message
        for message in invalid_model.observed_messages[1]
        if isinstance(message, ToolMessage)
    ]
    assert invalid_result.status == "completed"
    assert json.loads(invalid_returned[0].content) == {"ok": False, "error": "invalid_arguments"}


def test_side_effecting_multi_tool_batch_is_rejected_without_writing(
    make_runner, agent_context, workspace
) -> None:
    runner, model = make_runner(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "write_file",
                        "args": {"path": "drafts/out.txt", "content": "secret draft"},
                        "id": "write-1",
                        "type": "tool_call",
                    },
                    {
                        "name": "list_dir",
                        "args": {"path": ""},
                        "id": "list-2",
                        "type": "tool_call",
                    },
                ],
            ),
            AIMessage(content="The conflicting batch was rejected."),
        ]
    )
    result = run_agent(runner, "Inspect and save a draft.", agent_context)
    returned = [
        message for message in model.observed_messages[1] if isinstance(message, ToolMessage)
    ]
    assert result.status == "completed"
    assert len(returned) == 2
    assert all(
        json.loads(message.content)["error"] == "unsafe_parallel_batch" for message in returned
    )
    assert not (workspace / "drafts" / "out.txt").exists()


def test_tool_round_limit_stops_before_executing_an_extra_model_decision(
    make_runner, agent_context
) -> None:
    limits = AgentLimits(model_timeout_seconds=1, max_tool_rounds=1, task_timeout_seconds=2)
    runner, _model = make_runner(
        [
            tool_call("list_dir", {"path": "inputs"}, "list-1"),
            tool_call("read_file", {"path": "inputs/news.md"}, "read-2"),
        ],
        limits=limits,
    )
    result = run_agent(runner, "Inspect the task materials.", agent_context)

    assert result.status == "limited"
    assert result.termination_reason == "iteration_limit"
    assert result.tool_rounds == 1
    assert execution_names(result) == ["list_dir"]


def test_oversized_tool_call_batch_is_limited_without_partial_execution(
    make_runner, agent_context
) -> None:
    limits = AgentLimits(
        model_timeout_seconds=1,
        max_tool_rounds=2,
        max_calls_per_round=1,
        task_timeout_seconds=2,
    )
    batch = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "list_dir",
                "args": {"path": "inputs"},
                "id": f"call-{index}",
                "type": "tool_call",
            }
            for index in range(2)
        ],
    )
    runner, _model = make_runner([batch], limits=limits)
    result = run_agent(runner, "Inspect the workspace.", agent_context)
    assert result.status == "limited"
    assert result.termination_reason == "tool_call_limit"
    assert execution_names(result) == []


def test_model_timeout_and_task_deadline_have_distinct_terminations(
    make_runner, agent_context
) -> None:
    model_limited, _ = make_runner(
        [AIMessage(content="too late")],
        delay=0.05,
        limits=AgentLimits(model_timeout_seconds=0.005, max_tool_rounds=1, task_timeout_seconds=1),
    )
    model_result = run_agent(model_limited, "Wait for a reply.", agent_context)
    assert model_result.status == "failed"
    assert model_result.termination_reason == "model_timeout"

    task_limited, _ = make_runner(
        [AIMessage(content="too late")],
        delay=0.1,
        limits=AgentLimits(model_timeout_seconds=1, max_tool_rounds=1, task_timeout_seconds=0.01),
    )
    task_result = run_agent(task_limited, "Wait for a reply.", agent_context)
    assert task_result.status == "limited"
    assert task_result.termination_reason == "deadline"


def test_final_answer_without_tool_calls_completes_immediately(make_runner, agent_context) -> None:
    runner, model = make_runner(
        [
            AIMessage(
                content="No tool was needed.",
                usage_metadata={"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            )
        ]
    )
    result = run_agent(runner, "Say whether tools are necessary.", agent_context)
    assert result.status == "completed"
    assert result.termination_reason == "final_answer"
    assert result.final_answer == "No tool was needed."
    assert result.tool_rounds == 0
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert result.events[0].input_tokens == 12
    assert result.events[0].output_tokens == 4
    assert len(model.observed_messages) == 1


def test_trace_redacts_arguments_and_does_not_capture_tool_content(
    make_runner, agent_context
) -> None:
    runner, _model = make_runner(
        [
            tool_call(
                "write_file",
                {
                    "path": "drafts/private.md",
                    "content": "this exact secret text must not be logged",
                },
                "write-secret-1",
            ),
            AIMessage(content="Draft saved."),
        ]
    )
    result = run_agent(runner, "Save the draft.", agent_context)
    serialized = result.model_dump_json()
    assert result.status == "completed"
    assert "this exact secret text" not in serialized
    assert "drafts/private.md" not in serialized
    assert "write-secret-1" in serialized


def test_agent_factory_requires_complete_model_configuration() -> None:
    from app.agent.model import create_chat_model
    from app.core.config import Settings

    with pytest.raises(ModelNotConfiguredError, match="llm_not_configured"):
        create_agent(settings=Settings(llm_api_key=None, llm_base_url=None, llm_model=None))

    with pytest.raises(ModelNotConfiguredError, match="llm_not_configured"):
        create_chat_model(
            Settings(
                llm_api_key="replace_me",
                llm_base_url="https://api.example.com/v1",
                llm_model="replace_with_model_id",
            )
        )
    with pytest.raises(ModelNotConfiguredError, match="llm_not_configured"):
        create_chat_model(
            Settings(
                llm_api_key="test-only-key",
                llm_base_url="https://user:password@proxy.example/v1",
                llm_model="model-id",
            )
        )
