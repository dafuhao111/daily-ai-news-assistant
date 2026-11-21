import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.task_context import ToolFailure
from app.models.news import NewsItemRecord, RSSSourceRecord, utc_now
from app.news.schemas import NewsArticle, RSSSource

logger = logging.getLogger(__name__)


def _to_database_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _from_database_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _record_to_article(record: NewsItemRecord) -> NewsArticle:
    return NewsArticle(
        article_id=record.article_id,
        url_hash=record.url_hash,
        source_id=record.source_id,
        source_name=record.source_name_snapshot,
        category=record.category,
        title=record.title,
        summary=record.summary,
        url=record.original_url,
        canonical_url=record.canonical_url,
        published_at_raw=record.published_at_raw,
        published_at_utc=_from_database_time(record.published_at_utc),
        published_at_field=record.published_at_field,
        fetched_at_utc=_from_database_time(record.fetched_at_utc) or "",
        article_text=record.content_excerpt,
        article_text_truncated=record.content_truncated,
    )


class NewsRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def sync_sources(self, sources: tuple[RSSSource, ...]) -> None:
        enabled_ids = {source.source_id for source in sources if source.enabled}
        try:
            with self.session_factory() as session:
                records = {
                    record.source_id: record for record in session.scalars(select(RSSSourceRecord))
                }
                for record in records.values():
                    if record.source_id not in enabled_ids:
                        record.enabled = False
                for source in sources:
                    record = records.get(source.source_id)
                    if record is None:
                        record = RSSSourceRecord(source_id=source.source_id)
                        session.add(record)
                    record.name = source.name
                    record.feed_url = source.feed_url
                    record.allowed_hosts = source.allowed_hosts
                    record.category = source.category
                    record.enabled = source.enabled
                session.commit()
        except SQLAlchemyError as error:
            logger.warning("news source sync failed (%s)", type(error).__name__)
            raise ToolFailure("database_unavailable") from error

    def record_source_fetch(self, source_id: str, error_code: str | None = None) -> None:
        try:
            with self.session_factory() as session:
                source = session.get(RSSSourceRecord, source_id)
                if source is None:
                    raise ToolFailure("source_not_configured")
                source.last_fetch_at = utc_now()
                source.last_error_code = error_code
                session.commit()
        except SQLAlchemyError as error:
            logger.warning("news source status update failed (%s)", type(error).__name__)
            raise ToolFailure("database_unavailable") from error

    def save_candidates(
        self,
        source: RSSSource,
        articles: list[NewsArticle],
    ) -> tuple[list[NewsArticle], int]:
        active: list[NewsArticle] = []
        included_skipped = 0
        try:
            with self.session_factory() as session:
                if session.get(RSSSourceRecord, source.source_id) is None:
                    raise ToolFailure("source_not_configured")
                for article in articles:
                    record = session.scalar(
                        select(NewsItemRecord).where(NewsItemRecord.url_hash == article.url_hash)
                    )
                    if record is None:
                        record = NewsItemRecord(
                            article_id=article.article_id,
                            source_id=source.source_id,
                            source_name_snapshot=source.name,
                            category=source.category,
                            canonical_url=article.canonical_url,
                            url_hash=article.url_hash,
                            original_url=article.url,
                            title=article.title,
                            summary=article.summary,
                            published_at_utc=_to_database_time(article.published_at_utc),
                            published_at_raw=article.published_at_raw,
                            published_at_field=article.published_at_field,
                            fetched_at_utc=_to_database_time(article.fetched_at_utc) or utc_now(),
                        )
                        try:
                            with session.begin_nested():
                                session.add(record)
                                session.flush()
                        except IntegrityError:
                            record = session.scalar(
                                select(NewsItemRecord).where(
                                    NewsItemRecord.url_hash == article.url_hash
                                )
                            )
                            if record is None:
                                raise
                    elif record.included_at is None:
                        record.fetched_at_utc = (
                            _to_database_time(article.fetched_at_utc) or utc_now()
                        )

                    if record is None:
                        continue
                    if record.included_at is not None:
                        included_skipped += 1
                    else:
                        active.append(_record_to_article(record))
                session.commit()
        except ToolFailure:
            raise
        except SQLAlchemyError as error:
            logger.warning("news candidate save failed (%s)", type(error).__name__)
            raise ToolFailure("database_unavailable") from error
        return active, included_skipped

    def pending_candidates(self, source_id: str, limit: int = 50) -> list[NewsArticle]:
        try:
            with self.session_factory() as session:
                records = session.scalars(
                    select(NewsItemRecord)
                    .where(
                        NewsItemRecord.source_id == source_id,
                        NewsItemRecord.included_at.is_(None),
                    )
                    .order_by(NewsItemRecord.fetched_at_utc.asc())
                    .limit(limit)
                )
                return [_record_to_article(record) for record in records]
        except SQLAlchemyError as error:
            logger.warning("pending news lookup failed (%s)", type(error).__name__)
            raise ToolFailure("database_unavailable") from error

    def save_article_text(self, article_id: str, article_text: str, truncated: bool) -> None:
        try:
            with self.session_factory() as session:
                record = session.scalar(
                    select(NewsItemRecord).where(NewsItemRecord.article_id == article_id)
                )
                if record is None:
                    raise ToolFailure("article_not_found")
                record.content_excerpt = article_text
                record.content_truncated = truncated
                record.fetched_at_utc = utc_now()
                session.commit()
        except ToolFailure:
            raise
        except SQLAlchemyError as error:
            logger.warning("article text save failed (%s)", type(error).__name__)
            raise ToolFailure("database_unavailable") from error

    @staticmethod
    def mark_task_success(
        session: Session,
        article_ids: list[str],
        source_cursors: dict[str, str],
    ) -> None:
        """Apply inclusion and cursor changes inside the caller's brief transaction."""
        if article_ids:
            session.execute(
                update(NewsItemRecord)
                .where(NewsItemRecord.article_id.in_(article_ids))
                .values(included_at=utc_now())
            )
        for source_id, cursor in source_cursors.items():
            source = session.get(RSSSourceRecord, source_id)
            if source is None:
                raise ToolFailure("source_not_configured")
            source.last_successful_cursor = cursor[:1024]
