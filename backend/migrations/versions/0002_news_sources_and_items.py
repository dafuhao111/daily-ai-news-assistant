"""Add configured RSS sources and deduplicated news items."""

import sqlalchemy as sa
from alembic import op

revision = "0002_news_sources_items"
down_revision = "0001_profile_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rss_source",
        sa.Column("source_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("feed_url", sa.Text(), nullable=False),
        sa.Column("allowed_hosts", sa.JSON(), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_fetch_at", sa.DateTime(), nullable=True),
        sa.Column("last_successful_cursor", sa.String(length=1024), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "news_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("source_name_snapshot", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("published_at_utc", sa.DateTime(), nullable=True),
        sa.Column("published_at_raw", sa.String(length=240), nullable=True),
        sa.Column("published_at_field", sa.String(length=20), nullable=True),
        sa.Column("fetched_at_utc", sa.DateTime(), nullable=False),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("content_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("included_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["rss_source.source_id"]),
    )
    op.create_index("ix_news_item_source_id", "news_item", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_news_item_source_id", table_name="news_item")
    op.drop_table("news_item")
    op.drop_table("rss_source")
