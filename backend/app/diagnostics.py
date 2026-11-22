"""Local developer-only tool trace, with no prompts, arguments, recipients or payloads.

Run from backend/: uv run --locked python -m app.diagnostics RUN_ID
"""

import argparse
import json

from sqlalchemy import select

from app.application.profiles import LOCAL_USER_ID
from app.models.brief import BriefRecord, TaskRunRecord, ToolCallRecord


def inspect_run(session_factory, run_id: str) -> dict:
    with session_factory() as session:
        run = session.get(TaskRunRecord, run_id)
        if run is None or run.user_id != LOCAL_USER_ID:
            return {"error": "run_not_found"}
        calls = list(
            session.scalars(
                select(ToolCallRecord)
                .where(ToolCallRecord.run_id == run_id)
                .order_by(ToolCallRecord.attempt, ToolCallRecord.iteration, ToolCallRecord.id)
            )
        )
        brief_id = session.scalar(select(BriefRecord.id).where(BriefRecord.run_id == run_id))
        return {
            "run_id": run_id,
            "model_decisions": [
                {
                    key: event[key]
                    for key in ("turn", "kind", "status", "requested_tools", "duration_ms")
                    if key in event
                }
                for event in (run.usage_json or {}).get("model_decisions", [])[:128]
                if isinstance(event, dict)
            ],
            "model_tool_calls": [
                {
                    "attempt": call.attempt,
                    "iteration": call.iteration,
                    "call_id": call.call_id,
                    "tool": call.tool_name,
                }
                for call in calls
            ],
            "tool_results": [
                {
                    "call_id": call.call_id,
                    "attempt": call.attempt,
                    "status": call.status,
                    "error_code": call.error_code,
                    "duration_ms": call.duration_ms,
                }
                for call in calls
            ],
            "final_result": {
                "status": run.status,
                "error_code": run.error_code,
                "brief_id": brief_id,
            },
            "usage": {
                key: value
                for key, value in (run.usage_json or {}).items()
                if key in {"model_turns", "tool_rounds", "input_tokens", "output_tokens"}
                and isinstance(value, int)
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read a persisted local Agent trace without secrets"
    )
    parser.add_argument("run_id")
    args = parser.parse_args()
    from app.main import app

    factory = app.state.session_factory
    if factory is None:
        parser.exit(1, "database_not_configured\n")
    print(json.dumps(inspect_run(factory, args.run_id), ensure_ascii=False, indent=2))
    app.state.engine.dispose()


if __name__ == "__main__":
    main()
