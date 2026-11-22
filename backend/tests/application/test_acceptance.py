import asyncio

import pytest
from sqlalchemy import select

from app.acceptance import run_acceptance
from app.core.config import Settings
from app.main import create_app
from app.models.brief import TaskRunRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile


def test_acceptance_guard_and_configuration_restore_on_task_failure(engine, session_factory):
    from datetime import time

    with session_factory.begin() as session:
        session.add(
            UserProfile(
                id=1,
                display_name="Test",
                recipient_email="test@example.org",
                mail_test_status="succeeded",
            )
        )
        session.flush()
        session.add(
            SubscriptionPreferences(
                user_id=1,
                topics=["Agent 与工具"],
                keywords=[],
                excluded_keywords=[],
                timezone="Asia/Shanghai",
                run_time=time(8, 30),
                enabled=False,
            )
        )
    app = create_app(Settings(scheduler_enabled=False, smtp_max_attempts=1), engine)

    class Configured:
        is_configured = True

    app.state.smtp_mailer = Configured()

    class FailingCoordinator:
        async def execute_queued(self, run_id):
            with session_factory.begin() as session:
                session.get(TaskRunRecord, run_id).status = "failed"

        def _fail_queued(self, *_args):
            pass

    app.state.task_coordinator = FailingCoordinator()
    result = asyncio.run(run_acceptance(app, send_email=True))
    assert result["final_result"]["status"] == "failed"
    assert result["delivery_attempts"] == 0
    with session_factory() as session:
        assert session.get(SubscriptionPreferences, 1).enabled is False
        assert session.scalar(select(TaskRunRecord)).preferences_snapshot["enabled"] is True
    app.state.settings.scheduler_enabled = True
    with pytest.raises(RuntimeError, match="acceptance_requires"):
        asyncio.run(run_acceptance(app, send_email=True))
