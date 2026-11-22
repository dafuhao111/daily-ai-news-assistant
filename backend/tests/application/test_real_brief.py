import asyncio
import os
from datetime import date, time

import httpx
import pytest
from sqlalchemy import select

from app.agent import AgentLimits, AgentRunner
from app.agent.model import create_chat_model
from app.application.briefs import BriefGenerationService
from app.core.config import Settings
from app.core.task_context import ToolContext
from app.models.brief import TaskRunRecord, ToolCallRecord
from app.models.profile import UserProfile
from app.news.repository import NewsRepository
from app.news.service import NewsService
from app.schemas.preferences import PreferencesWrite
from app.tools import create_default_registry


@pytest.mark.real_llm
def test_real_model_generates_a_brief_from_mock_rss(
    tmp_path, session_factory, rss_source, response_handler, public_resolver, record_property
) -> None:
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

    with session_factory.begin() as session:
        session.add(UserProfile(id=1, display_name="Test Reader", role="AI researcher"))
    repository = NewsRepository(session_factory)
    repository.sync_sources((rss_source,))
    for directory in ("inputs", "history", "drafts"):
        (tmp_path / directory).mkdir()
    context = ToolContext(
        run_id="real-brief-check",
        workspace_root=tmp_path,
        news_sources=(rss_source,),
        news_repository=repository,
    )
    runner = AgentRunner(
        model=create_chat_model(settings),
        registry=create_default_registry(
            news_service=NewsService(
                transport=httpx.MockTransport(response_handler),
                resolver=public_resolver,
            )
        ),
        limits=AgentLimits(
            model_timeout_seconds=settings.agent_model_timeout_seconds,
            max_tool_rounds=6,
            task_timeout_seconds=120,
        ),
    )
    preferences = PreferencesWrite(
        topics=["Agent 与工具"],
        keywords=["Agent"],
        excluded_keywords=[],
        run_time=time(8, 30),
        timezone="Asia/Shanghai",
        enabled=False,
    )

    brief = asyncio.run(
        BriefGenerationService(runner, session_factory).generate(
            preferences,
            context,
            date(2026, 11, 21),
        )
    )

    assert brief.run_status in {"completed", "empty"}
    with session_factory() as session:
        usage = session.get(TaskRunRecord, brief.run_id).usage_json
        record_property("input_tokens", usage["input_tokens"])
        record_property("output_tokens", usage["output_tokens"])
        calls = session.scalars(select(ToolCallRecord).where(ToolCallRecord.run_id == brief.run_id))
        assert "fetch_rss" in {call.tool_name for call in calls}
