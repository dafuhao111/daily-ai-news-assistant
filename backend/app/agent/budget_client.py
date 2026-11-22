"""Budget guard at the HTTP boundary, covering direct adapter calls as well as Agents."""

import asyncio
import json

import httpx
from sqlalchemy import create_engine

from app.application.budget import BudgetError, TokenBudgetService
from app.db.session import build_session_factory


class BudgetHTTPClient(httpx.AsyncClient):
    def __init__(self, source, settings, *, budget_service=None, owns_source=False):
        super().__init__()
        self.source = source
        self.settings = settings
        self.budget_service = budget_service
        self.owns_source = owns_source
        self.budget_engine = None

    def ledger(self):
        if self.budget_service is None:
            if not self.settings.database_url:
                raise BudgetError("budget_storage_unavailable")
            options = {"pool_pre_ping": True}
            if self.settings.database_url.startswith("mysql+pymysql:"):
                options["connect_args"] = {
                    "connect_timeout": 5,
                    "read_timeout": 10,
                    "write_timeout": 10,
                }
            self.budget_engine = create_engine(self.settings.database_url, **options)
            self.budget_service = TokenBudgetService(build_session_factory(self.budget_engine))
        return self.budget_service

    async def send(self, request, **kwargs):
        # Standard text/tool JSON only. Both configured protocols use these fields.
        # No provider-managed conversation IDs or media that could hide input usage.
        try:
            body = json.loads(request.content)
        except (ValueError, UnicodeError):
            raise BudgetError("budget_request_unsupported") from None
        if (
            not isinstance(body, dict)
            or body.get("stream")
            or body.get("n", 1) != 1
            or any(
                key in body for key in ("previous_response_id", "conversation", "file_ids", "audio")
            )
        ):
            raise BudgetError("budget_request_unsupported")
        limit = body.get(
            "max_output_tokens", body.get("max_completion_tokens", body.get("max_tokens"))
        )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= self.settings.llm_max_output_tokens
        ):
            raise BudgetError("budget_output_limit_missing")
        # UTF-8 request bytes conservatively account for all messages, tools,
        # arguments and repeated history, plus provider framing allowance. This is
        # explicitly a reserve, not an exact tokenizer or a billing guarantee.
        reserve = len(request.content) + limit + self.settings.llm_budget_request_allowance_tokens
        ledger = self.ledger()
        request_id = await asyncio.to_thread(ledger.reserve, reserve)
        try:
            response = await self.source.send(request, **kwargs)
            await response.aread()
            if not response.is_success:
                raise BudgetError("budget_request_uncertain")
            try:
                payload = response.json()
                usage = payload.get("usage") if isinstance(payload, dict) else None
                if not isinstance(usage, dict):
                    raise TypeError
                input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
                output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
                total = usage.get("total_tokens")
                if total is not None and (
                    not isinstance(total, int)
                    or isinstance(total, bool)
                    or not isinstance(input_tokens, int)
                    or not isinstance(output_tokens, int)
                    or total != input_tokens + output_tokens
                ):
                    raise ValueError
            except (ValueError, TypeError):
                raise BudgetError("budget_usage_missing") from None
            await asyncio.to_thread(
                ledger.settle, request_id, input_tokens, output_tokens, max_output_tokens=limit
            )
            return response
        except BaseException:
            # Includes cancellation/model timeout. Never refund an ambiguous send.
            # A crash before this transaction leaves its reservation held instead.
            ledger.mark_uncertain(request_id)
            raise

    async def aclose(self):
        try:
            if self.owns_source:
                await self.source.aclose()
        finally:
            await super().aclose()
            if self.budget_engine is not None:
                self.budget_engine.dispose()
