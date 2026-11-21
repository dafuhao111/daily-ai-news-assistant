from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolContext:
    run_id: str
    workspace_root: Path


class ToolFailure(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
