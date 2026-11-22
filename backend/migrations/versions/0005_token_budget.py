"""Durable project-wide model token reservations and usage ledger."""

import sqlalchemy as sa
from alembic import op

revision = "0005_token_budget"
down_revision = "0004_mail_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "token_budget",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("limit_tokens", sa.BigInteger(), nullable=False),
        sa.Column("confirmed_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column("uncertain_tokens", sa.BigInteger(), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "token_usage",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("budget_id", sa.Integer(), sa.ForeignKey("token_budget.id"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
    )
    # Deliberately no resettable seed. Initialize from verified local history
    # using the explicit CLI before permitting a real model request.


def downgrade() -> None:
    op.drop_table("token_usage")
    op.drop_table("token_budget")
