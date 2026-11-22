"""One project budget shared by all real model requests, users and processes.

No prompts, URLs, keys, provider response IDs or raw payloads are persisted.
Reservations survive timeouts and restarts; they are never freed by a timer.
"""

from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.models.budget import TokenBudgetRecord, TokenUsageRecord
from app.models.profile import utc_now


class BudgetError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10**12


class TokenBudgetService:
    def __init__(self, session_factory, *, account_id=1):
        self.session_factory = session_factory
        self.account_id = account_id
        self.baseline_id = f"historical-baseline:{account_id}"

    def initialize(self, limit: int, prior_confirmed: int = 0, prior_uncertain: int = 0):
        if not all(_count(x) for x in (limit, prior_confirmed, prior_uncertain)) or limit == 0:
            raise BudgetError("budget_invalid_amount")
        try:
            with self.session_factory.begin() as session:
                if session.get(TokenBudgetRecord, self.account_id) is not None:
                    raise BudgetError("budget_already_initialized")
                session.add(
                    TokenBudgetRecord(
                        id=self.account_id,
                        limit_tokens=limit,
                        confirmed_tokens=prior_confirmed,
                        reserved_tokens=0,
                        uncertain_tokens=prior_uncertain,
                        blocked=False,
                    )
                )
                session.flush()
                session.add(
                    TokenUsageRecord(
                        id=self.baseline_id,
                        budget_id=self.account_id,
                        status="baseline",
                        reserved_tokens=prior_uncertain,
                        input_tokens=prior_confirmed,
                        output_tokens=0,
                        error_code="historical_usage_unconfirmed" if prior_uncertain else None,
                        settled_at=utc_now(),
                    )
                )
        except SQLAlchemyError:
            raise BudgetError("budget_storage_unavailable") from None

    def status(self):
        try:
            with self.session_factory() as session:
                budget = session.get(TokenBudgetRecord, self.account_id)
                if budget is None:
                    return {
                        "initialized": False,
                        "blocked": True,
                        "error_code": "budget_not_initialized",
                    }
                occupied = (
                    budget.confirmed_tokens + budget.reserved_tokens + budget.uncertain_tokens
                )
                return {
                    "initialized": True,
                    "limit_tokens": budget.limit_tokens,
                    "confirmed_tokens": budget.confirmed_tokens,
                    "reserved_tokens": budget.reserved_tokens,
                    "uncertain_tokens": budget.uncertain_tokens,
                    "available_tokens": max(0, budget.limit_tokens - occupied),
                    "blocked": budget.blocked or occupied >= budget.limit_tokens,
                }
        except SQLAlchemyError:
            raise BudgetError("budget_storage_unavailable") from None

    def reserve(self, amount: int) -> str:
        if not _count(amount) or not amount:
            raise BudgetError("budget_invalid_amount")
        request_id = str(uuid4())
        try:
            with self.session_factory.begin() as session:
                # Atomic conditional update works with MySQL row locks and SQLite.
                # It cannot grant two concurrent requests the same remaining tokens.
                result = session.execute(
                    update(TokenBudgetRecord)
                    .where(
                        TokenBudgetRecord.id == self.account_id,
                        TokenBudgetRecord.blocked.is_(False),
                        TokenBudgetRecord.confirmed_tokens
                        + TokenBudgetRecord.reserved_tokens
                        + TokenBudgetRecord.uncertain_tokens
                        + amount
                        <= TokenBudgetRecord.limit_tokens,
                    )
                    .values(reserved_tokens=TokenBudgetRecord.reserved_tokens + amount)
                )
                if result.rowcount != 1:
                    budget = session.get(TokenBudgetRecord, self.account_id)
                    raise BudgetError(
                        "budget_not_initialized"
                        if budget is None
                        else "budget_reconciliation_required"
                        if budget.blocked
                        else "budget_limit"
                    )
                session.add(
                    TokenUsageRecord(
                        id=request_id,
                        budget_id=self.account_id,
                        status="reserved",
                        reserved_tokens=amount,
                    )
                )
        except SQLAlchemyError:
            raise BudgetError("budget_storage_unavailable") from None
        return request_id

    def settle(
        self,
        request_id: str,
        input_tokens,
        output_tokens,
        *,
        reconcile=False,
        max_output_tokens=None,
    ):
        if not _count(input_tokens) or not _count(output_tokens):
            self.mark_uncertain(request_id, "budget_usage_missing")
            raise BudgetError("budget_usage_missing")
        total = input_tokens + output_tokens
        overrun = False
        try:
            with self.session_factory.begin() as session:
                # Lock account first, always. Avoid account/ledger lock inversions.
                budget = session.scalar(
                    select(TokenBudgetRecord)
                    .where(TokenBudgetRecord.id == self.account_id)
                    .with_for_update()
                )
                if budget is None:
                    raise BudgetError("budget_not_initialized")
                usage = session.scalar(
                    select(TokenUsageRecord)
                    .where(
                        TokenUsageRecord.id == request_id,
                        TokenUsageRecord.budget_id == self.account_id,
                    )
                    .with_for_update()
                )
                if usage is None or request_id == self.baseline_id:
                    raise BudgetError("budget_request_not_found")
                if usage.status in {"settled", "reconciled"}:
                    if (usage.input_tokens, usage.output_tokens) != (input_tokens, output_tokens):
                        raise BudgetError("budget_usage_conflict")
                    return  # Idempotent response handling, never double charge.
                if usage.status not in {"reserved", "uncertain"}:
                    raise BudgetError("budget_request_not_found")
                if usage.status == "uncertain" and not reconcile:
                    raise BudgetError("budget_reconciliation_required")
                if usage.status == "reserved":
                    budget.reserved_tokens -= usage.reserved_tokens
                else:
                    budget.uncertain_tokens -= usage.reserved_tokens
                budget.confirmed_tokens += total
                overrun = total > usage.reserved_tokens or (
                    max_output_tokens is not None and output_tokens > max_output_tokens
                )
                budget.blocked = budget.blocked or overrun
                usage.status = "reconciled" if reconcile else "settled"
                usage.input_tokens, usage.output_tokens = input_tokens, output_tokens
                usage.error_code = "budget_reservation_exceeded" if overrun else None
                usage.settled_at = utc_now()
        except SQLAlchemyError:
            raise BudgetError("budget_storage_unavailable") from None
        if overrun:
            raise BudgetError("budget_reservation_exceeded")

    def mark_uncertain(self, request_id: str, code="budget_request_uncertain"):
        try:
            with self.session_factory.begin() as session:
                budget = session.scalar(
                    select(TokenBudgetRecord)
                    .where(TokenBudgetRecord.id == self.account_id)
                    .with_for_update()
                )
                usage = session.scalar(
                    select(TokenUsageRecord)
                    .where(
                        TokenUsageRecord.id == request_id,
                        TokenUsageRecord.budget_id == self.account_id,
                    )
                    .with_for_update()
                )
                if budget is None or usage is None or usage.status != "reserved":
                    return
                budget.reserved_tokens -= usage.reserved_tokens
                budget.uncertain_tokens += usage.reserved_tokens
                usage.status, usage.error_code = "uncertain", code
        except SQLAlchemyError:
            # A failed update leaves the original durable reservation in place.
            raise BudgetError("budget_storage_unavailable") from None

    def pending(self):
        with self.session_factory() as session:
            return [
                {
                    "request_id": row.id,
                    "status": row.status,
                    "held_tokens": row.reserved_tokens,
                    "error_code": row.error_code,
                    "created_at_utc": row.created_at.isoformat() + "Z",
                }
                for row in session.scalars(
                    select(TokenUsageRecord)
                    .where(
                        TokenUsageRecord.budget_id == self.account_id,
                        TokenUsageRecord.status.in_(("reserved", "uncertain", "baseline")),
                    )
                    .order_by(TokenUsageRecord.created_at)
                    .limit(100)
                )
            ]

    def reconcile_history(self, confirmed_total: int):
        if not _count(confirmed_total):
            raise BudgetError("budget_invalid_amount")
        with self.session_factory.begin() as session:
            budget = session.scalar(
                select(TokenBudgetRecord)
                .where(TokenBudgetRecord.id == self.account_id)
                .with_for_update()
            )
            baseline = session.get(TokenUsageRecord, self.baseline_id)
            if budget is None or baseline is None:
                raise BudgetError("budget_not_initialized")
            if baseline.status == "history_confirmed":
                if baseline.input_tokens != confirmed_total:
                    raise BudgetError("budget_usage_conflict")
                return
            if confirmed_total < baseline.input_tokens:
                raise BudgetError("budget_history_below_known_usage")
            difference = confirmed_total - baseline.input_tokens
            budget.confirmed_tokens += difference
            budget.uncertain_tokens -= baseline.reserved_tokens
            session.add(
                TokenUsageRecord(
                    id=str(uuid4()),
                    budget_id=self.account_id,
                    status="history_adjustment",
                    reserved_tokens=baseline.reserved_tokens,
                    input_tokens=difference,
                    output_tokens=0,
                    error_code="historical_reserve_reconciled",
                    settled_at=utc_now(),
                )
            )
            baseline.status, baseline.input_tokens = "history_confirmed", confirmed_total
            baseline.reserved_tokens = 0
            baseline.error_code = None
            baseline.settled_at = utc_now()

    def acknowledge_overrun(self):
        with self.session_factory.begin() as session:
            budget = session.scalar(
                select(TokenBudgetRecord)
                .where(TokenBudgetRecord.id == self.account_id)
                .with_for_update()
            )
            if budget is None:
                raise BudgetError("budget_not_initialized")
            if (
                budget.reserved_tokens
                or budget.uncertain_tokens
                or budget.confirmed_tokens >= budget.limit_tokens
            ):
                raise BudgetError("budget_reconciliation_required")
            if budget.blocked:
                budget.blocked = False
                session.add(
                    TokenUsageRecord(
                        id=str(uuid4()),
                        budget_id=self.account_id,
                        status="acknowledged",
                        reserved_tokens=0,
                        input_tokens=0,
                        output_tokens=0,
                        error_code="provider_overrun_acknowledged",
                        settled_at=utc_now(),
                    )
                )
