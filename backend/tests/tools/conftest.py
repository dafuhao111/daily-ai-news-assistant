from pathlib import Path

import pytest

from app.tools import ToolContext, create_default_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "history").mkdir()
    (tmp_path / "drafts").mkdir()
    (tmp_path / ".secrets").mkdir()
    (tmp_path / "inputs" / "news.md").write_text(
        "Agent research\nA second line about RSS feeds.\n", encoding="utf-8"
    )
    (tmp_path / "history" / "previous.json").write_text(
        '{"title": "Older Agent report"}', encoding="utf-8"
    )
    (tmp_path / ".secrets" / "credentials.json").write_text("never expose", encoding="utf-8")
    return tmp_path


@pytest.fixture
def tool_context(workspace: Path) -> ToolContext:
    return ToolContext(run_id="test-run", workspace_root=workspace)


@pytest.fixture
def tool_registry():
    return create_default_registry()
