import json
import subprocess

import pytest


def test_bash_runs_only_a_trusted_json_validator(tool_registry, tool_context) -> None:
    allowed_shape = tool_registry.execute(
        "bash", {"command": "python -m json.tool history/previous.json"}, tool_context
    )
    assert allowed_shape.ok
    assert allowed_shape.data["exit_code"] == 0
    assert json.loads(allowed_shape.data["stdout"]) == {"title": "Older Agent report"}


@pytest.mark.parametrize(
    ("command", "error_code"),
    [
        ("cmd /c whoami", "command_denied"),
        ("python -c print(1)", "command_denied"),
        ("python -m json.tool inputs/previous.json & whoami", "command_denied"),
        ("python -m json.tool inputs/../../outside.json", "path_denied"),
        ("python -m json.tool .secrets/credentials.json", "path_denied"),
        ("python -m json.tool https://example.com/file.json", "path_denied"),
    ],
)
def test_bash_denies_unknown_or_unsafe_commands(
    tool_registry, tool_context, command: str, error_code: str
) -> None:
    result = tool_registry.execute("bash", {"command": command}, tool_context)
    assert result.error_code == error_code


def test_bash_isolates_imports_and_strips_secrets(
    tool_registry, tool_context, workspace, monkeypatch
):
    monkeypatch.setenv("LLM_API_KEY", "never-inherit-this-key")
    (workspace / "json.py").write_text(
        "raise RuntimeError('untrusted cwd module')", encoding="utf-8"
    )
    assert tool_registry.execute(
        "bash", {"command": "python -m json.tool history/previous.json"}, tool_context
    ).ok
    recorded = {}
    real_run = subprocess.run

    def inspect(argv, **kwargs):
        recorded.update(kwargs)
        assert argv[1:] == ["-I", "-S", "-m", "json.tool"]
        return real_run(argv, **kwargs)

    monkeypatch.setattr("app.tools.commands.subprocess.run", inspect)
    assert tool_registry.execute(
        "bash", {"command": "python -m json.tool history/previous.json"}, tool_context
    ).ok
    assert recorded["shell"] is False
    assert "LLM_API_KEY" not in recorded["env"]
    assert recorded["timeout"] == 2.0
    assert recorded["cwd"] == workspace.resolve()


def test_bash_timeout_invalid_and_oversized_inputs(
    tool_registry, tool_context, workspace, monkeypatch
):
    path = workspace / "inputs" / "check.json"
    path.write_text("{bad}", encoding="utf-8")
    assert (
        tool_registry.execute(
            "bash", {"command": "python -m json.tool inputs/check.json"}, tool_context
        ).error_code
        == "invalid_json"
    )
    path.write_text("[" * 34 + "0" + "]" * 34, encoding="utf-8")
    assert (
        tool_registry.execute(
            "bash", {"command": "python -m json.tool inputs/check.json"}, tool_context
        ).error_code
        == "json_depth_limit"
    )
    path.write_text('"' + "x" * 70000 + '"', encoding="utf-8")
    assert (
        tool_registry.execute(
            "bash", {"command": "python -m json.tool inputs/check.json"}, tool_context
        ).error_code
        == "file_too_large"
    )

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr("app.tools.commands.subprocess.run", timeout)
    assert (
        tool_registry.execute(
            "bash", {"command": "python -m json.tool history/previous.json"}, tool_context
        ).error_code
        == "execution_timeout"
    )


def test_bash_output_is_bounded(tool_registry, tool_context, workspace):
    (workspace / "inputs" / "large.json").write_text(
        json.dumps(list(range(4000))), encoding="utf-8"
    )
    result = tool_registry.execute(
        "bash", {"command": "python -m json.tool inputs/large.json"}, tool_context
    )
    assert result.ok and result.data["truncated"]
    assert len(result.data["stdout"].encode()) <= 4096
