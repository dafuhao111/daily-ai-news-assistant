import re
import shlex

from app.tools.context import ToolContext, ToolFailure
from app.tools.filesystem import _safe_target

SHELL_META = re.compile(r"[;&|><`$\n\r]")


def run_restricted_command(command: str, context: ToolContext) -> dict[str, object]:
    if SHELL_META.search(command):
        raise ToolFailure("command_denied")
    try:
        parts = shlex.split(command, posix=True)
    except ValueError as error:
        raise ToolFailure("invalid_command") from error
    if len(parts) != 4 or parts[:3] != ["python", "-m", "json.tool"]:
        raise ToolFailure("command_denied")
    _, path, _ = _safe_target(parts[3], context, access="read_file")
    if not path.is_file():
        raise ToolFailure("not_found")
    # Windows process isolation has not been verified, so no command is launched here.
    raise ToolFailure("sandbox_unavailable")
