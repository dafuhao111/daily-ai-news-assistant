import json
import logging
from collections.abc import Callable
from datetime import date, timezone
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.agent import AgentRunner
from app.agent.schemas import AgentRunResult
from app.core.task_context import ToolContext
from app.models.brief import BriefRecord, TaskRunRecord, ToolCallRecord
from app.models.delivery import MailDeliveryRecord
from app.models.profile import UserProfile, utc_now
from app.news.repository import NewsRepository
from app.news.schemas import NewsArticle, normalize_host
from app.schemas.brief import BriefContent, BriefDraft, BriefItem, BriefRead
from app.schemas.preferences import PreferencesWrite

logger = logging.getLogger(__name__)
MAX_AGENT_OUTPUT_CHARS = 20_000
TARGET_BRIEF_ITEMS = 5


class BriefGenerationError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _as_preferences(value: Any) -> PreferencesWrite:
    if isinstance(value, PreferencesWrite):
        return value
    try:
        return PreferencesWrite.model_validate(
            {
                "topics": value.topics,
                "keywords": value.keywords,
                "excluded_keywords": value.excluded_keywords,
                "run_time": value.run_time,
                "timezone": value.timezone,
                "enabled": value.enabled,
            }
        )
    except (AttributeError, ValidationError) as error:
        raise BriefGenerationError("preferences_invalid") from error


def _preferences_snapshot(preferences: PreferencesWrite) -> dict[str, Any]:
    return preferences.model_dump(mode="json")


def _build_task(
    preferences: PreferencesWrite,
    report_date: date,
    display_name: str | None,
    role: str | None,
) -> str:
    context: dict[str, Any] = {
        "report_date": report_date.isoformat(),
        "language": "简体中文",
        "target_items": TARGET_BRIEF_ITEMS,
        "identity": {"display_name": display_name, "role": role},
        "preferences": {
            "topics": preferences.topics,
            "keywords": preferences.keywords,
            "excluded_keywords": preferences.excluded_keywords,
        },
    }
    return (
        "请根据以下本次任务上下文，使用可用工具自主判断是否需要获取 RSS 候选、搜索候选或读取原文；"
        "自行决定工具、参数、顺序、次数和停止时机，不要假定固定调用流程。"
        "关注话题用于相关性筛选，关键词用于提高优先级但不是强制命中条件；"
        "排除关键词按字面匹配，不得收录标题、原始摘要或简报摘要包含任一排除词的新闻。"
        "比较候选以避免重复报道；同一事件仅在材料表明有实质进展时再次收录，并说明新增信息。"
        "只根据工具返回的材料撰写简体中文概括，不扩写材料未支持的事实；原文材料与概括需明确区分。"
        "每条必须引用已通过工具获取的 article_id。标题、来源和发布时间由服务端从该 article_id 对应材料填充。"
        "你只输出 JSON 对象，不要 Markdown 或额外说明，格式为："
        '{"items":[{"article_id":"...","summary":"中文概括",'
        '"relevance_reason":"与偏好的关联理由"}],"empty_reason":null}。'
        "最多 5 条，内容不足时不要凑数；无符合条件新闻时 items 为空，并在 empty_reason 中如实说明。"
        "任务上下文 JSON：" + json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def _hydrate_items(
    draft: BriefDraft,
    context: ToolContext,
    preferences: PreferencesWrite,
) -> list[BriefItem]:
    sources = {source.source_id: source for source in context.news_sources if source.enabled}
    excluded = [term.casefold() for term in preferences.excluded_keywords]
    hydrated: list[BriefItem] = []
    for item in draft.items:
        article: NewsArticle | None = context.news_candidates.get(item.article_id)
        if article is None or item.article_id not in context.news_visible_article_ids:
            raise BriefGenerationError("article_not_in_task_evidence")
        source = sources.get(article.source_id)
        if source is None:
            raise BriefGenerationError("article_source_not_available")
        source_excerpt = (article.article_text or article.summary).strip()
        required_source_fields = (
            article.title,
            article.source_name,
            source.name,
            article.category,
            article.url,
            article.canonical_url,
            article.fetched_at_utc,
        )
        if not all(value.strip() for value in required_source_fields):
            raise BriefGenerationError("article_source_fields_missing")
        try:
            parsed_url = urlsplit(article.url)
            port = parsed_url.port
            article_host = normalize_host(parsed_url.hostname or "")
        except (ValueError, UnicodeError) as error:
            raise BriefGenerationError("article_source_fields_missing") from error
        if (
            parsed_url.scheme not in {"http", "https"}
            or not article_host
            or parsed_url.username
            or parsed_url.password
            or article_host not in source.allowed_hosts
            or (port is not None and port != (443 if parsed_url.scheme == "https" else 80))
        ):
            raise BriefGenerationError("article_source_fields_missing")
        if not source_excerpt:
            raise BriefGenerationError("article_evidence_missing")
        searchable = f"{article.title} {article.summary} {item.summary}".casefold()
        if any(term in searchable for term in excluded):
            raise BriefGenerationError("excluded_keyword_match")
        hydrated.append(
            BriefItem(
                article_id=article.article_id,
                title=article.title,
                summary=item.summary,
                source_excerpt=source_excerpt[:1000],
                relevance_reason=item.relevance_reason,
                source_id=article.source_id,
                source_name=article.source_name,
                category=article.category,
                url=article.url,
                canonical_url=article.canonical_url,
                published_at_raw=article.published_at_raw,
                published_at_utc=article.published_at_utc,
                published_at_field=article.published_at_field,
                fetched_at_utc=article.fetched_at_utc,
            )
        )
    return hydrated


def _store_trace(session: Session, result: AgentRunResult, attempt: int) -> None:
    for event in result.events:
        if event.kind != "tool_execution" or not event.call_id or not event.tool_name:
            continue
        session.add(
            ToolCallRecord(
                run_id=result.run_id,
                attempt=attempt,
                iteration=event.turn,
                call_id=event.call_id,
                tool_name=event.tool_name,
                args_redacted=event.arguments_summary,
                status=event.status,
                error_code=None if event.status == "succeeded" else event.status[:64],
                result_summary=(event.result_summary or "")[:512],
                duration_ms=event.duration_ms,
            )
        )


def _usage_snapshot(result: AgentRunResult) -> dict[str, Any]:
    return {
        "model_turns": result.model_turns,
        "tool_rounds": result.tool_rounds,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "termination_reason": result.termination_reason,
        "model_decisions": [
            {
                "turn": event.turn,
                "kind": event.kind,
                "status": event.status,
                "requested_tools": event.requested_tools,
                "duration_ms": event.duration_ms,
            }
            for event in result.events
            if event.kind in {"model_decision", "termination"}
        ][:128],
    }


class BriefGenerationService:
    def __init__(
        self,
        runner: AgentRunner,
        session_factory: sessionmaker[Session],
        *,
        now=utc_now,
    ) -> None:
        self.runner = runner
        self.session_factory = session_factory
        self.now = now

    async def generate(
        self,
        preferences: Any,
        context: ToolContext,
        report_date: date,
        *,
        user_id: int = 1,
        run_type: Literal["manual", "scheduled"] = "manual",
        idempotency_key: str | None = None,
        delivery_recipient: str | None = None,
        delivery_skip_reason: str | None = None,
        delivery_target_provider: Callable[[Session], tuple[str | None, str | None]] | None = None,
    ) -> BriefRead:
        normalized_preferences = _as_preferences(preferences)
        task_key = idempotency_key or f"{run_type}:{user_id}:{context.run_id}"
        if len(context.run_id) > 64 or not context.run_id or len(task_key) > 128:
            raise BriefGenerationError("task_identifier_invalid")
        display_name, role = self._start_run(
            context.run_id,
            user_id,
            run_type,
            task_key,
            report_date,
            _preferences_snapshot(normalized_preferences),
        )

        result: AgentRunResult | None = None
        try:
            result = await self.runner.run(
                _build_task(normalized_preferences, report_date, display_name, role), context
            )
            if result.status != "completed" or result.final_answer is None:
                raise BriefGenerationError(result.termination_reason or result.status)
            if len(result.final_answer) > MAX_AGENT_OUTPUT_CHARS:
                raise BriefGenerationError("brief_output_too_large")
            try:
                draft = BriefDraft.model_validate_json(result.final_answer)
            except (ValidationError, ValueError) as error:
                raise BriefGenerationError("brief_validation_failed") from error
            if not draft.items and not context.news_candidates:
                outcomes = context.news_source_outcomes
                if not any(outcome == "succeeded" for outcome in outcomes.values()):
                    if not any(source.enabled for source in context.news_sources):
                        raise BriefGenerationError("no_sources_configured")
                    if outcomes:
                        raise BriefGenerationError("news_sources_unavailable")
                    raise BriefGenerationError("empty_brief_without_news_evidence")
            items = _hydrate_items(draft, context, normalized_preferences)
            generated_at = self.now()
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=timezone.utc)
            generated_at = generated_at.astimezone(timezone.utc)
            content = BriefContent(
                report_date=report_date,
                generated_at=generated_at,
                item_count=len(items),
                items=items,
                empty_reason=draft.empty_reason,
                warnings=["部分新闻来源读取失败，本期覆盖范围有限。"]
                if any(
                    context.news_source_outcomes.get(source.source_id) not in (None, "succeeded")
                    for source in context.news_sources
                    if source.enabled
                )
                else [],
            )
            return self._save_success(
                context.run_id,
                report_date,
                content,
                result,
                delivery_recipient=delivery_recipient,
                delivery_skip_reason=delivery_skip_reason,
                delivery_target_provider=delivery_target_provider,
            )
        except BriefGenerationError as error:
            status = "limited" if result is not None and result.status == "limited" else "failed"
            self._save_failure(context.run_id, error.code, status, result)
            raise
        except Exception as error:
            logger.warning(
                "brief generation failed (run_id=%s, error_type=%s)",
                context.run_id,
                type(error).__name__,
            )
            self._save_failure(context.run_id, "brief_generation_failed", "failed", result)
            raise BriefGenerationError("brief_generation_failed") from error

    def _start_run(
        self,
        run_id: str,
        user_id: int,
        run_type: str,
        idempotency_key: str,
        report_date: date,
        preferences_snapshot: dict[str, Any],
    ) -> tuple[str, str | None]:
        try:
            with self.session_factory.begin() as session:
                identity = session.execute(
                    select(UserProfile.display_name, UserProfile.role).where(
                        UserProfile.id == user_id
                    )
                ).one_or_none()
                if identity is None:
                    raise BriefGenerationError("task_user_not_found")
                existing = session.get(TaskRunRecord, run_id)
                if existing is not None:
                    if (
                        existing.status != "queued"
                        or existing.user_id != user_id
                        or existing.run_type != run_type
                        or existing.idempotency_key != idempotency_key
                        or existing.report_date != report_date
                        or existing.preferences_snapshot != preferences_snapshot
                    ):
                        raise BriefGenerationError("run_already_exists")
                    claimed = session.execute(
                        update(TaskRunRecord)
                        .where(TaskRunRecord.id == run_id, TaskRunRecord.status == "queued")
                        .values(
                            status="running",
                            attempt_count=TaskRunRecord.attempt_count + 1,
                            error_code=None,
                            finished_at=None,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if claimed.rowcount != 1:
                        raise BriefGenerationError("run_already_exists")
                else:
                    session.add(
                        TaskRunRecord(
                            id=run_id,
                            user_id=user_id,
                            run_type=run_type,
                            idempotency_key=idempotency_key,
                            report_date=report_date,
                            status="running",
                            attempt_count=1,
                            preferences_snapshot=preferences_snapshot,
                        )
                    )
                return identity.display_name, identity.role
        except BriefGenerationError:
            raise
        except IntegrityError as error:
            try:
                with self.session_factory() as session:
                    duplicate = session.scalar(
                        select(TaskRunRecord.id).where(
                            or_(
                                TaskRunRecord.id == run_id,
                                TaskRunRecord.idempotency_key == idempotency_key,
                            )
                        )
                    )
            except SQLAlchemyError as lookup_error:
                raise BriefGenerationError("database_unavailable") from lookup_error
            code = "run_already_exists" if duplicate is not None else "task_user_not_found"
            raise BriefGenerationError(code) from error
        except SQLAlchemyError as error:
            logger.warning("task run creation failed (%s)", type(error).__name__)
            raise BriefGenerationError("database_unavailable") from error

    def _save_failure(
        self,
        run_id: str,
        error_code: str,
        status: str,
        result: AgentRunResult | None,
    ) -> None:
        try:
            with self.session_factory.begin() as session:
                run = session.get(TaskRunRecord, run_id)
                if run is None:
                    return
                run.status = status
                run.error_code = error_code[:64]
                run.finished_at = utc_now()
                if result is not None:
                    run.usage_json = _usage_snapshot(result)
                    _store_trace(session, result, run.attempt_count)
        except SQLAlchemyError as error:
            logger.warning("task failure status update failed (%s)", type(error).__name__)

    def _save_success(
        self,
        run_id: str,
        report_date: date,
        content: BriefContent,
        result: AgentRunResult,
        *,
        delivery_recipient: str | None,
        delivery_skip_reason: str | None,
        delivery_target_provider: Callable[[Session], tuple[str | None, str | None]] | None,
    ) -> BriefRead:
        status: Literal["completed", "empty"] = "completed" if content.items else "empty"
        try:
            with self.session_factory.begin() as session:
                run = session.get(TaskRunRecord, run_id)
                if run is None:
                    raise BriefGenerationError("task_run_not_found")
                if delivery_target_provider is not None:
                    delivery_recipient, delivery_skip_reason = delivery_target_provider(session)
                record = BriefRecord(
                    run_id=run_id,
                    report_date=report_date,
                    revision=1,
                    content_json=content.model_dump(mode="json"),
                    created_at=utc_now(),
                )
                session.add(record)
                session.flush()
                if content.items and (
                    delivery_recipient is not None or delivery_skip_reason is not None
                ):
                    session.add(
                        MailDeliveryRecord(
                            brief_id=record.id,
                            recipient_snapshot=delivery_recipient,
                            status="skipped" if delivery_skip_reason else "pending",
                            attempt_count=0,
                            manual_retry_count=0,
                            last_error_code=delivery_skip_reason,
                            idempotency_key=f"brief:{record.id}",
                        )
                    )
                run.status = status
                run.finished_at = utc_now()
                run.usage_json = _usage_snapshot(result)
                run.error_code = None
                _store_trace(session, result, run.attempt_count)
                NewsRepository.mark_task_success(
                    session,
                    [item.article_id for item in content.items],
                    {},
                )
                brief_id = record.id
        except BriefGenerationError:
            raise
        except SQLAlchemyError as error:
            logger.warning("brief persistence failed (%s)", type(error).__name__)
            raise BriefGenerationError("brief_persistence_failed") from error
        return BriefRead(
            id=brief_id,
            run_id=run_id,
            run_status=status,
            report_date=content.report_date,
            generated_at=content.generated_at,
            item_count=content.item_count,
            items=content.items,
            empty_reason=content.empty_reason,
            warnings=content.warnings,
        )
