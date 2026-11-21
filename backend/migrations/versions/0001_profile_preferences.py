"""Create the single-user profile and subscription preference tables."""

import sqlalchemy as sa
from alembic import op

revision = "0001_profile_preferences"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("role", sa.String(length=120), nullable=True),
        sa.Column("recipient_email", sa.String(length=254), nullable=True),
        sa.Column(
            "mail_test_status",
            sa.String(length=24),
            server_default="unconfigured",
            nullable=False,
        ),
        sa.Column("mail_tested_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "subscription_preferences",
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("excluded_keywords", sa.JSON(), nullable=False),
        sa.Column("run_time", sa.Time(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user_profile.id"]),
    )


def downgrade() -> None:
    op.drop_table("subscription_preferences")
    op.drop_table("user_profile")
