from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentTask(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    task: str = Field(min_length=1, max_length=10_000)


class AgentTraceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence: int
    turn: int
    kind: Literal["model_decision", "tool_execution", "termination"]
    status: str
    tool_name: str | None = None
    call_id: str | None = None
    requested_tools: list[str] = Field(default_factory=list)
    arguments_summary: dict[str, str] = Field(default_factory=dict)
    result_summary: str | None = None
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class AgentRunResult(BaseModel):
    run_id: str
    status: Literal["completed", "limited", "failed"]
    termination_reason: str
    final_answer: str | None = None
    model_turns: int = 0
    tool_rounds: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    events: list[AgentTraceEvent] = Field(default_factory=list)
