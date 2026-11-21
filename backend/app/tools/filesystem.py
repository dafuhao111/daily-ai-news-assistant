import hashlib
import os
import re
import stat
import tempfile
import time
from pathlib import Path, PureWindowsPath
from typing import Any

from app.tools.context import ToolContext, ToolFailure

READ_ROOTS = {"inputs", "history"}
READ_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".xml", ".html", ".htm", ".yaml", ".yml"}
WRITE_EXTENSIONS = {".txt", ".md", ".json"}
DENIED_NAMES = {
    ".env",
    ".git",
    ".secrets",
    "credentials",
    "secrets",
    "logs",
    "tokens.json",
    "token.json",
}
SENSITIVE_NAME_MARKERS = (
    "credential",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "api_key",
    "apikey",
    "private_key",
    "id_rsa",
)
MAX_FILE_BYTES = 65_536
MAX_DIRECTORY_ENTRIES = 100
MAX_DIRECTORY_SCAN_ENTRIES = 500
MAX_SEARCH_FILES = 200
MAX_SEARCH_DIRECTORIES = 200
MAX_SEARCH_BYTES = 4 * 1024 * 1024
MAX_SEARCH_RESULTS = 50
MAX_DEPTH = 8
MAX_RUNTIME_SECONDS = 2.0
MAX_SNIPPET_CHARS = 240


def _file_attributes(path: Path) -> int:
    try:
        return path.lstat().st_file_attributes
    except (AttributeError, OSError):
        return 0


def _is_reparse_point(path: Path) -> bool:
    return bool(_file_attributes(path) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _is_external_hard_link(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_nlink > 1
    except OSError:
        return True


def _is_hidden_name(name: str) -> bool:
    folded = name.casefold()
    return (
        name.startswith(".")
        or folded in DENIED_NAMES
        or folded.startswith(("credentials.", "token.", "tokens."))
        or any(marker in folded for marker in SENSITIVE_NAME_MARKERS)
        or Path(folded).suffix in {".key", ".pem", ".p12", ".pfx", ".token"}
    )


def _validate_relative_path(raw_path: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(raw_path, str) or "\x00" in raw_path:
        raise ToolFailure("invalid_path")
    normalized = raw_path.strip().replace("/", "\\")
    if not normalized and allow_empty:
        return ()
    windows_path = PureWindowsPath(normalized)
    if (
        not normalized
        or windows_path.is_absolute()
        or windows_path.drive
        or normalized.startswith(("\\\\", "/"))
    ):
        raise ToolFailure("path_denied")
    parts = tuple(part for part in normalized.split("\\") if part not in ("", "."))
    if not parts or any(part == ".." or ":" in part or _is_hidden_name(part) for part in parts):
        raise ToolFailure("path_denied")
    if len(parts) > MAX_DEPTH:
        raise ToolFailure("path_denied")
    return parts


def _workspace_root(context: ToolContext) -> Path:
    root = Path(context.workspace_root)
    try:
        if not root.exists() or not root.is_dir() or root.is_symlink() or _is_reparse_point(root):
            raise ToolFailure("workspace_unavailable")
        return root.resolve(strict=True)
    except OSError as error:
        raise ToolFailure("workspace_unavailable") from error


def _safe_target(
    raw_path: str,
    context: ToolContext,
    *,
    access: str,
    allow_empty: bool = False,
    create_parents: bool = False,
) -> tuple[Path, Path, tuple[str, ...]]:
    parts = _validate_relative_path(raw_path, allow_empty=allow_empty)
    root = _workspace_root(context)
    if access in {"read", "read_file"} and (not parts or parts[0].casefold() not in READ_ROOTS):
        raise ToolFailure("path_denied")
    if access == "write_file" and (len(parts) < 2 or parts[0].casefold() != "drafts"):
        raise ToolFailure("path_denied")
    if access == "read_file" and Path(parts[-1]).suffix.casefold() not in READ_EXTENSIONS:
        raise ToolFailure("file_type_denied")
    if access == "write_file" and Path(parts[-1]).suffix.casefold() not in WRITE_EXTENSIONS:
        raise ToolFailure("file_type_denied")

    target = root.joinpath(*parts)
    if not parts:
        return root, root, parts
    cursor = root
    for index, part in enumerate(parts):
        cursor = cursor / part
        if cursor.is_symlink() or _is_reparse_point(cursor):
            raise ToolFailure("path_denied")
        is_last = index == len(parts) - 1
        if not is_last and not cursor.exists() and create_parents:
            try:
                cursor.mkdir()
            except FileExistsError:
                pass
        if cursor.exists():
            try:
                resolved = cursor.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError) as error:
                raise ToolFailure("path_denied") from error
        elif not is_last and not create_parents:
            raise ToolFailure("not_found")
    try:
        target.parent.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as error:
        raise ToolFailure("path_denied") from error
    return root, target, parts


def _metadata(path: Path, parts: tuple[str, ...]) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": "/".join(parts),
        "type": "directory" if path.is_dir() else "file",
    }


def list_directory(raw_path: str, context: ToolContext) -> dict[str, Any]:
    _, directory, parts = _safe_target(raw_path, context, access="list", allow_empty=True)
    if not directory.exists():
        raise ToolFailure("not_found")
    if not directory.is_dir():
        raise ToolFailure("not_a_directory")
    entries: list[dict[str, Any]] = []
    scan_truncated = False
    try:
        for scanned, entry in enumerate(os.scandir(directory), start=1):
            if scanned > MAX_DIRECTORY_SCAN_ENTRIES:
                scan_truncated = True
                break
            if _is_hidden_name(entry.name) or entry.is_symlink():
                continue
            path = Path(entry.path)
            if _is_reparse_point(path):
                continue
            if path.is_file() and _is_external_hard_link(path):
                continue
            entry_parts = (*parts, entry.name)
            entries.append(_metadata(path, entry_parts))
            if len(entries) > MAX_DIRECTORY_ENTRIES:
                break
    except OSError as error:
        raise ToolFailure("read_failed") from error
    entries.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
    truncated = scan_truncated or len(entries) > MAX_DIRECTORY_ENTRIES
    return {
        "path": "/".join(parts),
        "entries": entries[:MAX_DIRECTORY_ENTRIES],
        "truncated": truncated,
    }


def read_text_file(raw_path: str, context: ToolContext) -> dict[str, Any]:
    _, path, parts = _safe_target(raw_path, context, access="read_file")
    if not path.exists():
        raise ToolFailure("not_found")
    if not path.is_file():
        raise ToolFailure("not_a_file")
    if _is_external_hard_link(path):
        raise ToolFailure("path_denied")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ToolFailure("file_too_large")
    try:
        with path.open("rb") as file:
            content = file.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        raise ToolFailure("read_failed") from error
    if len(content) > MAX_FILE_BYTES:
        raise ToolFailure("file_too_large")
    if b"\x00" in content:
        raise ToolFailure("binary_file_denied")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ToolFailure("invalid_encoding") from error
    return {
        "path": "/".join(parts),
        "content": text,
        "sha256": hashlib.sha256(content).hexdigest(),
        "truncated": False,
    }


def _walk_material_files(directory: Path, relative_parts: tuple[str, ...], deadline: float):
    pending = [(directory, relative_parts)]
    visited_directories = 0
    while pending:
        if time.monotonic() >= deadline:
            raise ToolFailure("execution_timeout")
        visited_directories += 1
        if visited_directories > MAX_SEARCH_DIRECTORIES:
            raise ToolFailure("search_limit")
        current, parts = pending.pop()
        if len(parts) >= MAX_DEPTH:
            continue
        try:
            children = os.scandir(current)
        except OSError as error:
            raise ToolFailure("read_failed") from error
        with children:
            for entry_count, entry in enumerate(children, start=1):
                if time.monotonic() >= deadline:
                    raise ToolFailure("execution_timeout")
                if entry_count > MAX_DIRECTORY_ENTRIES:
                    raise ToolFailure("search_limit")
                if _is_hidden_name(entry.name) or entry.is_symlink():
                    continue
                path = Path(entry.path)
                if _is_reparse_point(path):
                    continue
                child_parts = (*parts, entry.name)
                if entry.is_dir(follow_symlinks=False):
                    pending.append((path, child_parts))
                elif entry.is_file(follow_symlinks=False) and not _is_external_hard_link(path):
                    yield path, child_parts


def search_text(keyword: str, raw_dir: str, context: ToolContext) -> dict[str, Any]:
    if not keyword.strip() or len(keyword) > 200:
        raise ToolFailure("invalid_arguments")
    _, directory, parts = _safe_target(raw_dir, context, access="read")
    if not directory.exists():
        raise ToolFailure("not_found")
    if not directory.is_dir():
        raise ToolFailure("not_a_directory")

    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    total_bytes = 0
    scanned_files = 0
    matches: list[dict[str, Any]] = []
    needle = keyword.casefold()
    for path, file_parts in _walk_material_files(directory, parts, deadline):
        if time.monotonic() >= deadline:
            raise ToolFailure("execution_timeout")
        if path.suffix.casefold() not in READ_EXTENSIONS:
            continue
        scanned_files += 1
        if scanned_files > MAX_SEARCH_FILES:
            return {"matches": matches, "match_count": len(matches), "truncated": True}
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_SEARCH_BYTES:
            return {"matches": matches, "match_count": len(matches), "truncated": True}
        if size > MAX_FILE_BYTES:
            continue
        try:
            with path.open("rb") as file:
                raw = file.read(MAX_FILE_BYTES + 1)
            if len(raw) > MAX_FILE_BYTES:
                continue
            if b"\x00" in raw:
                continue
            content = raw.decode("utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if needle not in line.casefold():
                continue
            snippet = re.sub(r"\s+", " ", line).strip()[:MAX_SNIPPET_CHARS]
            matches.append({"path": "/".join(file_parts), "line": line_number, "snippet": snippet})
            if len(matches) >= MAX_SEARCH_RESULTS:
                return {"matches": matches, "match_count": len(matches), "truncated": True}
    return {"matches": matches, "match_count": len(matches), "truncated": False}


def write_draft(raw_path: str, content: str, context: ToolContext) -> dict[str, Any]:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ToolFailure("file_too_large")
    _, path, parts = _safe_target(raw_path, context, access="write_file", create_parents=True)
    if path.exists() and not path.is_file():
        raise ToolFailure("not_a_file")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=".draft-", suffix=".tmp", delete=False
        ) as temporary:
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        if _is_reparse_point(path) or path.is_symlink():
            raise ToolFailure("path_denied")
        temporary_path.replace(path)
    except ToolFailure:
        raise
    except OSError as error:
        raise ToolFailure("write_failed") from error
    finally:
        if temporary_path is not None and temporary_path.exists():
            try:
                temporary_path.unlink()
            except OSError:
                pass
    return {"path": "/".join(parts), "bytes_written": len(encoded), "written": True}
