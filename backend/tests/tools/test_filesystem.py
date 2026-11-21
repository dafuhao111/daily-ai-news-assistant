import os
import subprocess

import pytest

from app.tools import filesystem


def test_list_dir_only_returns_visible_workspace_entries(tool_registry, tool_context) -> None:
    result = tool_registry.execute("list_dir", {"path": ""}, tool_context)
    assert result.ok
    names = {entry["name"] for entry in result.data["entries"]}
    assert {"inputs", "history", "drafts"} <= names
    assert ".secrets" not in names

    result = tool_registry.execute("list_dir", {"path": "inputs"}, tool_context)
    assert [entry["name"] for entry in result.data["entries"]] == ["news.md"]


def test_list_dir_caps_large_directories(tool_registry, workspace, tool_context) -> None:
    from app.tools.filesystem import MAX_DIRECTORY_ENTRIES

    for index in range(MAX_DIRECTORY_ENTRIES + 1):
        (workspace / "inputs" / f"item-{index:03}.txt").touch()
    result = tool_registry.execute("list_dir", {"path": "inputs"}, tool_context)
    assert len(result.data["entries"]) == MAX_DIRECTORY_ENTRIES
    assert result.data["truncated"] is True


def test_list_dir_caps_scanning_hidden_entries(tool_registry, workspace, tool_context) -> None:
    from app.tools.filesystem import MAX_DIRECTORY_ENTRIES, MAX_DIRECTORY_SCAN_ENTRIES

    for index in range(MAX_DIRECTORY_SCAN_ENTRIES + 1):
        (workspace / "inputs" / f".hidden-{index:03}.txt").touch()
    result = tool_registry.execute("list_dir", {"path": "inputs"}, tool_context)
    assert len(result.data["entries"]) <= MAX_DIRECTORY_ENTRIES
    assert result.data["truncated"] is True


@pytest.mark.parametrize("name", ["api_key.json", "smtp_password.txt", "article-secret.md"])
def test_sensitive_material_names_are_rejected(
    tool_registry, workspace, tool_context, name: str
) -> None:
    (workspace / "inputs" / name).write_text("do not expose", encoding="utf-8")
    result = tool_registry.execute("read_file", {"path": f"inputs/{name}"}, tool_context)
    assert result.error_code == "path_denied"


@pytest.mark.parametrize(
    "path",
    [
        "../outside.txt",
        "inputs/../../outside.txt",
        "C:\\secret.txt",
        "\\\\server\\share.txt",
        "/etc/passwd",
    ],
)
def test_file_paths_cannot_escape_workspace(tool_registry, tool_context, path: str) -> None:
    result = tool_registry.execute("read_file", {"path": path}, tool_context)
    assert not result.ok
    assert result.error_code == "path_denied"


@pytest.mark.parametrize(
    "path",
    [
        ".secrets/credentials.json",
        "inputs/credentials.json",
        "inputs/private.key",
        "inputs/.env.local",
    ],
)
def test_sensitive_files_are_never_read(tool_registry, workspace, tool_context, path: str) -> None:
    if path == "inputs/credentials.json":
        (workspace / path).write_text("secret", encoding="utf-8")
    elif path == "inputs/private.key":
        (workspace / path).write_text("key", encoding="utf-8")
    elif path == "inputs/.env.local":
        (workspace / path).write_text("secret", encoding="utf-8")
    result = tool_registry.execute("read_file", {"path": path}, tool_context)
    assert not result.ok
    assert result.error_code == "path_denied"


def test_read_file_returns_content_hash_and_encoding_error(
    tool_registry, workspace, tool_context
) -> None:
    result = tool_registry.execute("read_file", {"path": "inputs/news.md"}, tool_context)
    assert result.ok
    assert result.data["content"].startswith("Agent research")
    assert len(result.data["sha256"]) == 64
    assert result.data["truncated"] is False

    (workspace / "inputs" / "broken.txt").write_bytes(b"\xff\xfe")
    result = tool_registry.execute("read_file", {"path": "inputs/broken.txt"}, tool_context)
    assert result.error_code == "invalid_encoding"


def test_read_file_rejects_binary_and_oversized_files(
    tool_registry, workspace, tool_context
) -> None:
    (workspace / "inputs" / "binary.txt").write_bytes(b"a\x00b")
    (workspace / "inputs" / "large.txt").write_bytes(b"x" * 65_537)
    assert (
        tool_registry.execute("read_file", {"path": "inputs/binary.txt"}, tool_context).error_code
        == "binary_file_denied"
    )
    assert (
        tool_registry.execute("read_file", {"path": "inputs/large.txt"}, tool_context).error_code
        == "file_too_large"
    )


def test_search_content_is_local_and_bounded(tool_registry, tool_context) -> None:
    result = tool_registry.execute(
        "search_content", {"keyword": "agent", "dir": "inputs"}, tool_context
    )
    assert result.ok
    assert result.data["match_count"] == 1
    assert result.data["matches"][0]["path"] == "inputs/news.md"
    assert result.data["matches"][0]["line"] == 1

    denied = tool_registry.execute(
        "search_content", {"keyword": "secret", "dir": ".secrets"}, tool_context
    )
    assert denied.error_code == "path_denied"


def test_search_caps_file_count_and_result_count(tool_registry, workspace, tool_context) -> None:
    from app.tools.filesystem import MAX_SEARCH_RESULTS

    (workspace / "inputs" / "many.txt").write_text(
        "needle\n" * (MAX_SEARCH_RESULTS + 1), encoding="utf-8"
    )
    result = tool_registry.execute(
        "search_content", {"keyword": "needle", "dir": "inputs"}, tool_context
    )
    assert result.ok
    assert len(result.data["matches"]) == MAX_SEARCH_RESULTS
    assert result.data["truncated"] is True


def test_search_caps_scanned_files(tool_registry, workspace, tool_context, monkeypatch) -> None:
    monkeypatch.setattr(filesystem, "MAX_SEARCH_FILES", 1)
    (workspace / "inputs" / "extra.txt").write_text("no matching content", encoding="utf-8")
    result = tool_registry.execute(
        "search_content", {"keyword": "not-present", "dir": "inputs"}, tool_context
    )
    assert result.ok
    assert result.data["match_count"] == 0
    assert result.data["truncated"] is True


def test_search_stops_when_execution_budget_is_exhausted(
    tool_registry, tool_context, monkeypatch
) -> None:
    monkeypatch.setattr(filesystem, "MAX_RUNTIME_SECONDS", 0)
    result = tool_registry.execute(
        "search_content", {"keyword": "Agent", "dir": "inputs"}, tool_context
    )
    assert result.error_code == "execution_timeout"


def test_search_caps_directory_traversal(tool_registry, workspace, tool_context) -> None:
    from app.tools.filesystem import MAX_SEARCH_DIRECTORIES

    for index in range(MAX_SEARCH_DIRECTORIES + 1):
        (workspace / "inputs" / f"dir-{index:03}").mkdir()
    result = tool_registry.execute(
        "search_content", {"keyword": "Agent", "dir": "inputs"}, tool_context
    )
    assert result.error_code == "search_limit"


def test_write_file_only_writes_drafts_and_replaces_atomically(
    tool_registry, workspace, tool_context
) -> None:
    payload = {"path": "drafts/briefs/today.json", "content": '{"items": []}'}
    result = tool_registry.execute("write_file", payload, tool_context)
    assert result.ok
    assert result.data["written"] is True
    assert (workspace / payload["path"]).read_text(encoding="utf-8") == payload["content"]

    payload["content"] = '{"items": [1]}'
    assert tool_registry.execute("write_file", payload, tool_context).ok
    assert (workspace / payload["path"]).read_text(encoding="utf-8") == payload["content"]
    assert not list((workspace / "drafts" / "briefs").glob(".draft-*.tmp"))


@pytest.mark.parametrize(
    "path",
    ["inputs/overwrite.md", "drafts/../inputs/overwrite.md", "drafts/brief.exe"],
)
def test_write_file_refuses_paths_outside_draft_policy(
    tool_registry, workspace, tool_context, path: str
) -> None:
    result = tool_registry.execute("write_file", {"path": path, "content": "bad"}, tool_context)
    assert not result.ok
    assert not (workspace / "inputs" / "overwrite.md").exists()


def test_write_file_rejects_content_over_byte_limit(tool_registry, tool_context) -> None:
    result = tool_registry.execute(
        "write_file", {"path": "drafts/large.txt", "content": "新" * 30_000}, tool_context
    )
    assert result.error_code == "file_too_large"


def test_symlink_inside_workspace_cannot_reach_external_files(
    tool_registry, workspace, tool_context, tmp_path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("do not read", encoding="utf-8")
    try:
        os.symlink(outside, workspace / "inputs" / "linked", target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        (outside / "secret.txt").unlink(missing_ok=True)
        outside.rmdir()
        pytest.skip(f"symlink creation is unavailable: {error}")

    try:
        result = tool_registry.execute(
            "read_file", {"path": "inputs/linked/secret.txt"}, tool_context
        )
        assert result.error_code == "path_denied"
    finally:
        (workspace / "inputs" / "linked").unlink(missing_ok=True)
        (outside / "secret.txt").unlink(missing_ok=True)
        outside.rmdir()


def test_hard_link_inside_workspace_cannot_expose_external_file(
    tool_registry, workspace, tool_context, tmp_path
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    outside.write_text("external data", encoding="utf-8")
    link = workspace / "inputs" / "linked.txt"
    try:
        link.hardlink_to(outside)
    except OSError as error:
        pytest.skip(f"hard-link creation is unavailable: {error}")

    try:
        assert (
            tool_registry.execute(
                "read_file", {"path": "inputs/linked.txt"}, tool_context
            ).error_code
            == "path_denied"
        )
        listing = tool_registry.execute("list_dir", {"path": "inputs"}, tool_context)
        assert "linked.txt" not in {entry["name"] for entry in listing.data["entries"]}
    finally:
        outside.unlink(missing_ok=True)


def test_windows_junction_inside_workspace_cannot_reach_external_files(
    tool_registry, workspace, tool_context, tmp_path
) -> None:
    if os.name != "nt":
        pytest.skip("Windows junctions are only available on Windows")
    outside = tmp_path.parent / f"{tmp_path.name}-junction-target"
    outside.mkdir()
    (outside / "secret.txt").write_text("do not read", encoding="utf-8")
    junction = workspace / "inputs" / "junction"
    draft_junction = workspace / "drafts" / "external"
    completed = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if completed.returncode != 0:
        pytest.skip(f"junction creation is unavailable: {completed.stderr or completed.stdout}")
    draft_completed = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(draft_junction), str(outside)],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    if draft_completed.returncode != 0:
        subprocess.run(
            ["cmd.exe", "/c", "rmdir", str(junction)],
            capture_output=True,
            timeout=5,
            check=False,
        )
        pytest.skip(
            f"draft junction creation is unavailable: {draft_completed.stderr or draft_completed.stdout}"
        )

    try:
        result = tool_registry.execute(
            "read_file", {"path": "inputs/junction/secret.txt"}, tool_context
        )
        assert result.error_code == "path_denied"
        assert "junction" not in {
            entry["name"]
            for entry in tool_registry.execute("list_dir", {"path": "inputs"}, tool_context).data[
                "entries"
            ]
        }
        write_result = tool_registry.execute(
            "write_file",
            {"path": "drafts/external/escape.txt", "content": "no"},
            tool_context,
        )
        assert write_result.error_code == "path_denied"
    finally:
        for link in (junction, draft_junction):
            subprocess.run(
                ["cmd.exe", "/c", "rmdir", str(link)],
                capture_output=True,
                timeout=5,
                check=False,
            )
        (outside / "secret.txt").unlink(missing_ok=True)
        outside.rmdir()
