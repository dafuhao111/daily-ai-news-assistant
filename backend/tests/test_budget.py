import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.agent import AgentRunner
from app.agent.budget_client import BudgetHTTPClient
from app.application.budget import BudgetError, TokenBudgetService
from app.core.config import Settings
from app.models.budget import TokenUsageRecord
from app.tools import ToolContext, create_default_registry


@pytest.fixture
def ledger(session_factory):
    service = TokenBudgetService(session_factory)
    service.initialize(100_000, 100, 200)
    return service


def test_reserve_settle_idempotency_and_restart_persistence(ledger, session_factory):
    request_id = ledger.reserve(1000)
    assert ledger.status()["available_tokens"] == 98_700
    ledger.settle(request_id, 300, 20)
    ledger.settle(request_id, 300, 20)
    restarted = TokenBudgetService(session_factory)
    assert restarted.status() == {
        "initialized": True,
        "limit_tokens": 100_000,
        "confirmed_tokens": 420,
        "reserved_tokens": 0,
        "uncertain_tokens": 200,
        "available_tokens": 99_380,
        "blocked": False,
    }
    with pytest.raises(BudgetError, match="already_initialized"):
        restarted.initialize(1_000_000)
    with pytest.raises(BudgetError, match="usage_conflict"):
        ledger.settle(request_id, 0, 0)


def test_insufficient_uninitialized_missing_and_oversized_usage_fail_closed(
    session_factory, ledger
):
    with pytest.raises(BudgetError, match="budget_limit"):
        ledger.reserve(100_000)
    request_id = ledger.reserve(100)
    with pytest.raises(BudgetError, match="usage_missing"):
        ledger.settle(request_id, None, 4)
    assert ledger.status()["uncertain_tokens"] == 300
    assert ledger.status()["reserved_tokens"] == 0
    # Explicit provider-bill reconciliation frees only this held reservation.
    ledger.settle(request_id, 30, 10, reconcile=True)
    assert ledger.status()["confirmed_tokens"] == 140
    assert ledger.status()["uncertain_tokens"] == 200
    overrun = ledger.reserve(5)
    with pytest.raises(BudgetError, match="reservation_exceeded"):
        ledger.settle(overrun, 5, 1)
    assert ledger.status()["confirmed_tokens"] == 146
    with pytest.raises(BudgetError, match="reconciliation_required"):
        ledger.reserve(1)


def test_missing_account_never_starts_a_request(session_factory):
    ledger = TokenBudgetService(session_factory)
    assert ledger.status()["initialized"] is False
    with pytest.raises(BudgetError, match="not_initialized"):
        ledger.reserve(1)


def test_crashed_reservation_is_never_automatically_refunded(ledger, session_factory):
    request_id = ledger.reserve(99_700)
    restarted = TokenBudgetService(session_factory)
    assert restarted.status()["available_tokens"] == 0
    with pytest.raises(BudgetError, match="budget_limit"):
        restarted.reserve(1)
    restarted.mark_uncertain(request_id)
    restarted.mark_uncertain(request_id)
    assert restarted.status()["uncertain_tokens"] == 99_900
    assert restarted.status()["reserved_tokens"] == 0
    pending = restarted.pending()
    assert any(
        row["request_id"] == request_id and row["created_at_utc"].endswith("Z") for row in pending
    )


@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
def test_http_boundary_accounts_wire_usage_and_stops_before_network(ledger, protocol):
    observed = []

    def handle(request):
        observed.append(request)
        usage = (
            {"input_tokens": 100, "output_tokens": 10}
            if protocol == "responses"
            else {"prompt_tokens": 100, "completion_tokens": 10}
        )
        return httpx.Response(200, json={"usage": usage})

    async def exercise():
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as source,
            BudgetHTTPClient(source, Settings(_env_file=None), budget_service=ledger) as client,
        ):
            body = {
                "max_output_tokens" if protocol == "responses" else "max_completion_tokens": 128,
                "input": "text",
                "tools": [],
            }
            await client.post("https://gateway.example/v1/test", json=body)
            held = ledger.reserve(ledger.status()["available_tokens"])
            with pytest.raises(BudgetError, match="budget_limit"):
                await client.post("https://gateway.example/v1/test", json=body)
            assert len(observed) == 1
            assert ledger.status()["confirmed_tokens"] == 210
            ledger.mark_uncertain(held)

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["no_usage", "malformed", "timeout", "http_error", "cancel"])
def test_ambiguous_http_usage_stays_charged_and_private(ledger, outcome, session_factory):
    async def handle(request):
        if outcome == "timeout":
            raise httpx.ReadTimeout("private provider content", request=request)
        if outcome == "cancel":
            raise asyncio.CancelledError
        if outcome == "http_error":
            return httpx.Response(500, json={"error": "private provider content"})
        return httpx.Response(
            200,
            json={"usage": {"input_tokens": True, "output_tokens": 2}}
            if outcome == "malformed"
            else {},
        )

    async def exercise():
        async with (
            httpx.AsyncClient(transport=httpx.MockTransport(handle)) as source,
            BudgetHTTPClient(source, Settings(_env_file=None), budget_service=ledger) as client,
        ):
            with pytest.raises((BudgetError, httpx.ReadTimeout, asyncio.CancelledError)):
                await client.post(
                    "https://gateway.example/v1/responses",
                    json={"max_output_tokens": 128, "input": "private prompt"},
                )

    asyncio.run(exercise())
    status = ledger.status()
    assert status["reserved_tokens"] == 0 and status["uncertain_tokens"] > 200
    with session_factory() as session:
        rows = list(session.scalars(select(TokenUsageRecord)))
        assert rows[-1].status == "uncertain"
        assert "private" not in str(
            [{col.name: getattr(row, col.name) for col in row.__table__.columns} for row in rows]
        )


def test_budget_storage_failure_does_not_contact_provider(monkeypatch):
    observed = []

    async def exercise():
        async with (
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: observed.append(request))
            ) as source,
            BudgetHTTPClient(source, Settings(_env_file=None, database_url=None)) as client,
        ):
            with pytest.raises(BudgetError, match="storage_unavailable"):
                await client.post(
                    "https://gateway.example/v1/responses", json={"max_output_tokens": 128}
                )

    asyncio.run(exercise())
    assert observed == []


def test_agent_budget_guard_is_limited_before_fixed_or_fake_tools(tmp_path):
    class Model:
        def bind_tools(self, *args, **kwargs):
            return self

        async def ainvoke(self, _messages):
            try:
                raise BudgetError("budget_limit")
            except BudgetError as error:
                raise RuntimeError("SDK wrapper") from error

    result = asyncio.run(
        AgentRunner(Model(), create_default_registry()).run(
            "Produce news", ToolContext(run_id="budget-exhausted", workspace_root=tmp_path)
        )
    )
    assert result.status == "limited" and result.termination_reason == "budget_limit"
    assert not any(event.kind == "tool_execution" for event in result.events)


def test_budget_api_returns_only_safe_summary(client, local_headers):
    service = TokenBudgetService(client.app.state.session_factory)
    service.initialize(1_000_000, 118_771, 200_000)
    response = client.get("/api/v1/budget", headers=local_headers)
    assert response.status_code == 200
    assert response.json()["available_tokens"] == 681_229
    assert client.post(
        "/api/v1/budget", json={"limit": 999999999}, headers=local_headers
    ).status_code in (404, 405)


def test_history_reconciliation_is_explicit_idempotent_and_cannot_erase_known_usage(ledger):
    with pytest.raises(BudgetError, match="history_below_known_usage"):
        ledger.reconcile_history(99)
    ledger.reconcile_history(150)
    ledger.reconcile_history(150)
    assert ledger.status()["confirmed_tokens"] == 150
    assert ledger.status()["uncertain_tokens"] == 0
    with pytest.raises(BudgetError, match="usage_conflict"):
        ledger.reconcile_history(151)
    with pytest.raises(BudgetError, match="request_not_found"):
        ledger.settle(ledger.baseline_id, 1, 0, reconcile=True)


def test_overrun_acknowledgement_never_resets_usage_or_limit(ledger):
    request_id = ledger.reserve(1)
    with pytest.raises(BudgetError, match="reservation_exceeded"):
        ledger.settle(request_id, 2, 0)
    with pytest.raises(BudgetError, match="reconciliation_required"):
        ledger.acknowledge_overrun()
    ledger.reconcile_history(100)
    ledger.acknowledge_overrun()
    status = ledger.status()
    assert status["blocked"] is False
    assert status["confirmed_tokens"] == 102 and status["limit_tokens"] == 100_000


def test_provider_ignoring_output_cap_locks_future_requests_even_with_large_reserve(ledger):
    request_id = ledger.reserve(10_000)
    with pytest.raises(BudgetError, match="reservation_exceeded"):
        ledger.settle(request_id, 10, 200, max_output_tokens=128)
    assert ledger.status()["confirmed_tokens"] == 310
    assert ledger.status()["blocked"] is True


def test_total_usage_mismatch_is_held_instead_of_undercharged(ledger):
    async def exercise():
        async with (
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda _r: httpx.Response(
                        200,
                        json={
                            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 500}
                        },
                    )
                )
            ) as source,
            BudgetHTTPClient(source, Settings(_env_file=None), budget_service=ledger) as client,
        ):
            with pytest.raises(BudgetError, match="usage_missing"):
                await client.post(
                    "https://gateway.example/responses", json={"max_output_tokens": 128}
                )

    asyncio.run(exercise())
    assert ledger.status()["confirmed_tokens"] == 100
    assert ledger.status()["uncertain_tokens"] > 200


def test_two_mock_model_turns_are_individually_charged_and_budget_stops_new_request(
    session_factory, tmp_path
):
    from app.agent.model import create_chat_model

    ledger = TokenBudgetService(session_factory)
    ledger.initialize(1_000_000)
    observed = []

    def respond(request):
        observed.append(json.loads(request.content))
        if len(observed) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "chosen-by-model",
                        "type": "function",
                        "function": {"name": "list_dir", "arguments": '{"path":"inputs"}'},
                    }
                ],
            }
        else:
            message = {"role": "assistant", "content": "Done"}
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
            },
        )

    (tmp_path / "inputs").mkdir()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as source:
            model = create_chat_model(
                Settings(
                    _env_file=None,
                    llm_model="test-model",
                    llm_api_key="test-only",
                    llm_base_url="https://gateway.example/v1",
                ),
                http_async_client=source,
                budget_service=ledger,
            )
            return await AgentRunner(model, create_default_registry()).run(
                "Inspect inputs",
                ToolContext(run_id="accounted-model-decisions", workspace_root=tmp_path),
            )

    result = asyncio.run(exercise())
    assert result.status == "completed" and len(observed) == 2
    assert observed[1]["messages"][-1]["tool_call_id"] == "chosen-by-model"
    assert ledger.status()["confirmed_tokens"] == 220
    assert ledger.status()["reserved_tokens"] == 0
    assert [e.tool_name for e in result.events if e.kind == "tool_execution"] == ["list_dir"]
    held = ledger.reserve(ledger.status()["available_tokens"])
    blocked = asyncio.run(exercise())
    assert blocked.status == "limited" and blocked.termination_reason == "budget_limit"
    assert len(observed) == 2
    ledger.mark_uncertain(held)


def test_budget_can_stop_between_model_tool_rounds_without_a_fake_final_result(
    session_factory, tmp_path
):
    from app.agent.model import create_chat_model

    ledger = TokenBudgetService(session_factory)
    ledger.initialize(100_000)
    observed = []

    def respond(request):
        observed.append(request)
        reserved = ledger.status()["reserved_tokens"]
        ledger.reserve(ledger.status()["available_tokens"])
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "llm-list",
                                    "type": "function",
                                    "function": {
                                        "name": "list_dir",
                                        "arguments": '{"path":"inputs"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {
                    "prompt_tokens": reserved - 1,
                    "completion_tokens": 1,
                    "total_tokens": reserved,
                },
            },
        )

    (tmp_path / "inputs").mkdir()

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as source:
            model = create_chat_model(
                Settings(
                    _env_file=None,
                    llm_model="test-model",
                    llm_api_key="test-only",
                    llm_base_url="https://gateway.example/v1",
                ),
                http_async_client=source,
                budget_service=ledger,
            )
            return await AgentRunner(model, create_default_registry()).run(
                "Inspect inputs",
                ToolContext(run_id="budget-stops-next-turn", workspace_root=tmp_path),
            )

    result = asyncio.run(exercise())
    assert result.status == "limited" and result.termination_reason == "budget_limit"
    assert result.final_answer is None and len(observed) == 1
    assert [event.tool_name for event in result.events if event.kind == "tool_execution"] == [
        "list_dir"
    ]


def test_ledger_settlement_database_failure_keeps_reservation(session_factory, ledger, monkeypatch):
    from sqlalchemy.exc import OperationalError

    request_id = ledger.reserve(100)

    def broken():
        raise OperationalError("test-only", {}, None)

    with monkeypatch.context() as patch:
        patch.setattr(ledger.session_factory, "begin", broken)
        with pytest.raises(BudgetError, match="storage_unavailable"):
            ledger.settle(request_id, 10, 1)
    assert ledger.status()["reserved_tokens"] == 100


@pytest.mark.parametrize(
    "body",
    [
        {"stream": True, "max_tokens": 128},
        {"n": 2, "max_tokens": 128},
        {"previous_response_id": "hidden", "max_tokens": 128},
        {"max_tokens": None},
        {"max_tokens": 999999},
    ],
)
def test_unbounded_or_hidden_usage_requests_are_rejected_before_network(ledger, body):
    observed = []

    async def exercise():
        async with (
            httpx.AsyncClient(
                transport=httpx.MockTransport(lambda request: observed.append(request))
            ) as source,
            BudgetHTTPClient(source, Settings(_env_file=None), budget_service=ledger) as client,
        ):
            with pytest.raises(BudgetError):
                await client.post("https://gateway.example/responses", json=body)

    asyncio.run(exercise())
    assert observed == [] and ledger.status()["reserved_tokens"] == 0
