import pytest


def test_bash_is_registered_but_fail_closed_until_windows_sandbox_is_verified(
    tool_registry, tool_context
) -> None:
    allowed_shape = tool_registry.execute(
        "bash", {"command": "python -m json.tool history/previous.json"}, tool_context
    )
    assert allowed_shape.error_code == "sandbox_unavailable"


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
