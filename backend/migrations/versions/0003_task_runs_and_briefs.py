"""Add task runs, validated briefs, and redacted tool-call diagnostics."""

import sqlalchemy as sa
from alembic import op

revision = "0003_task_runs_briefs"
down_revision = "0002_news_sources_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_run",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("preferences_snapshot", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_task_run_user_report_date", "task_run", ["user_id", "report_date"])
    op.create_table(
        "brief",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["task_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index("ix_brief_report_date", "brief", ["report_date"])
    op.create_table(
        "tool_call",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("call_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=64), nullable=False),
        sa.Column("args_redacted", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("result_summary", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["task_run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "call_id", name="uq_tool_call_run_call"),
    )
    op.create_index("ix_tool_call_run_iteration", "tool_call", ["run_id", "iteration"])


def downgrade() -> None:
    op.drop_index("ix_tool_call_run_iteration", table_name="tool_call")
    op.drop_table("tool_call")
    op.drop_index("ix_brief_report_date", table_name="brief")
    op.drop_table("brief")
    op.drop_index("ix_task_run_user_report_date", table_name="task_run")
    op.drop_table("task_run")
