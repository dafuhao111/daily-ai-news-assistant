import os
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete

from app.application.budget import BudgetError, TokenBudgetService
from app.core.config import Settings
from app.db.session import build_session_factory
from app.models.budget import TokenBudgetRecord, TokenUsageRecord


@pytest.mark.mysql
def test_mysql_budget_concurrent_reservations_and_settlements_never_overspend():
    if os.getenv("RUN_MYSQL_TESTS") != "1":
        pytest.skip("set RUN_MYSQL_TESTS=1 for disposable-record MySQL budget test")
    settings = Settings()
    assert settings.database_url.startswith("mysql+pymysql:")
    engine = create_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"connect_timeout": 5}
    )
    factory = build_session_factory(engine)
    account_id = 1_000_000_000 + int(uuid4().hex[:7], 16)
    ledger = TokenBudgetService(factory, account_id=account_id)
    ledger.initialize(1000)
    barrier = threading.Barrier(8)
    try:

        def reserve(_index):
            barrier.wait(timeout=10)
            try:
                return ledger.reserve(600)
            except BudgetError as error:
                assert error.code == "budget_limit"
                return None

        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = [value for value in pool.map(reserve, range(8)) if value is not None]
        assert len(ids) == 1
        assert ledger.status()["reserved_tokens"] == 600
        barrier = threading.Barrier(8)

        def settle(_index):
            barrier.wait(timeout=10)
            ledger.settle(ids[0], 300, 100)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(settle, range(8)))
        assert ledger.status()["confirmed_tokens"] == 400
        assert ledger.status()["reserved_tokens"] == 0
        other = TokenBudgetService(factory, account_id=account_id)
        assert other.status()["available_tokens"] == 600
    finally:
        with factory.begin() as session:
            session.execute(
                delete(TokenUsageRecord).where(TokenUsageRecord.budget_id == account_id)
            )
            session.execute(delete(TokenBudgetRecord).where(TokenBudgetRecord.id == account_id))
        engine.dispose()
