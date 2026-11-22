import json
import os
import re
import shlex
import subprocess
import sys

from app.tools.context import ToolContext, ToolFailure
from app.tools.filesystem import _workspace_root, read_text_file

SHELL_META = re.compile(r"[;&|><`$\n\r]")
COMMAND_TIMEOUT_SECONDS = 2.0
MAX_OUTPUT_BYTES = 4096
MAX_JSON_DEPTH = 32


def run_restricted_command(command: str, context: ToolContext) -> dict[str, object]:
    if SHELL_META.search(command):
        raise ToolFailure("command_denied")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as error:
        raise ToolFailure("invalid_command") from error
    if len(parts) != 4 or parts[:3] != ["python", "-m", "json.tool"]:
        raise ToolFailure("command_denied")
    material = read_text_file(parts[3], context)
    if not material["path"].casefold().endswith(".json"):
        raise ToolFailure("command_denied")
    try:
        value = json.loads(material["content"])
    except (ValueError, RecursionError) as error:
        raise ToolFailure("invalid_json") from error
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ToolFailure("json_depth_limit")
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    # Only the trusted stdlib JSON formatter is launched. No shell or model argv,
    # no selected filename passed to the child, no site packages or cwd imports.
    # Size + depth limits bound pretty-print expansion before capture_output.
    environment = {"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {}
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-m", "json.tool"],
            input=material["content"].encode("utf-8"),
            cwd=_workspace_root(context),
            env=environment,
            shell=False,
            capture_output=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired as error:
        # subprocess.run kills and reaps this fixed, non-spawning child on timeout.
        raise ToolFailure("execution_timeout") from error
    except OSError as error:
        raise ToolFailure("command_unavailable") from error
    return {
        "exit_code": result.returncode,
        "stdout": result.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
        "stderr": "JSON validation failed." if result.returncode else "",
        "truncated": len(result.stdout) > MAX_OUTPUT_BYTES,
    }
