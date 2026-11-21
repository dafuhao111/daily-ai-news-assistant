"""Add durable mail delivery state and retry scheduling."""

import sqlalchemy as sa
from alembic import op

revision = "0004_mail_delivery"
down_revision = "0003_task_runs_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_run",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    with op.batch_alter_table("tool_call") as batch_op:
        batch_op.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_constraint("uq_tool_call_run_call", type_="unique")
        batch_op.create_unique_constraint(
            "uq_tool_call_run_attempt_call", ["run_id", "attempt", "call_id"]
        )
    op.create_table(
        "mail_delivery",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brief_id", sa.Integer(), nullable=False),
        sa.Column("recipient_snapshot", sa.String(length=254), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("manual_retry_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["brief_id"], ["brief.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("brief_id", name="uq_mail_delivery_brief"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_mail_delivery_due", "mail_delivery", ["status", "next_attempt_at"])


def downgrade() -> None:
    op.drop_index("ix_mail_delivery_due", table_name="mail_delivery")
    op.drop_table("mail_delivery")
    with op.batch_alter_table("tool_call") as batch_op:
        batch_op.drop_constraint("uq_tool_call_run_attempt_call", type_="unique")
        batch_op.drop_column("attempt")
        batch_op.create_unique_constraint("uq_tool_call_run_call", ["run_id", "call_id"])
    op.drop_column("task_run", "attempt_count")
