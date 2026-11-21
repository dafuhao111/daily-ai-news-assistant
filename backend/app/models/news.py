from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RSSSourceRecord(Base):
    __tablename__ = "rss_source"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    feed_url: Mapped[str] = mapped_column(Text, nullable=False)
    allowed_hosts: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_successful_cursor: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utc_now, onupdate=utc_now
    )


class NewsItemRecord(Base):
    __tablename__ = "news_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("rss_source.source_id"), nullable=False, index=True
    )
    source_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    published_at_utc: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    published_at_raw: Mapped[str | None] = mapped_column(String(240), nullable=True)
    published_at_field: Mapped[str | None] = mapped_column(String(20), nullable=True)
    fetched_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    included_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
