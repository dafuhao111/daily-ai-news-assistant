import asyncio
import logging
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.delivery.smtp import SMTPDeliveryFailure, SMTPMailer
from app.models.brief import BriefRecord, TaskRunRecord
from app.models.delivery import MailDeliveryRecord
from app.models.preferences import SubscriptionPreferences
from app.models.profile import UserProfile, utc_now
from app.schemas.brief import BriefContent, BriefRead

logger = logging.getLogger(__name__)
MAX_DUE_DELIVERIES_PER_SWEEP = 20
MAX_MANUAL_RETRIES = 3


class DeliveryError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MailDeliveryService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings,
        mailer: SMTPMailer,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.mailer = mailer

    def create_for_brief(
        self, brief_id: int, recipient: str | None, *, skipped: str | None = None
    ) -> int:
        key = f"brief:{brief_id}"
        try:
            with self.session_factory.begin() as session:
                existing = session.scalar(
                    select(MailDeliveryRecord).where(MailDeliveryRecord.brief_id == brief_id)
                )
                if existing is not None:
                    return existing.id
                record = MailDeliveryRecord(
                    brief_id=brief_id,
                    recipient_snapshot=recipient,
                    status="skipped" if skipped else "pending",
                    attempt_count=0,
                    manual_retry_count=0,
                    last_error_code=skipped,
                    idempotency_key=key,
                )
                session.add(record)
                session.flush()
                return record.id
        except IntegrityError as error:
            with self.session_factory() as session:
                record = session.scalar(
                    select(MailDeliveryRecord).where(MailDeliveryRecord.brief_id == brief_id)
                )
            if record is not None:
                return record.id
            raise DeliveryError("delivery_already_exists") from error
        except SQLAlchemyError as error:
            logger.warning("mail delivery creation failed (%s)", type(error).__name__)
            raise DeliveryError("database_unavailable") from error

    def get_for_brief(self, brief_id: int) -> tuple[int, str]:
        try:
            with self.session_factory() as session:
                record = session.scalar(
                    select(MailDeliveryRecord).where(MailDeliveryRecord.brief_id == brief_id)
                )
                if record is None:
                    raise DeliveryError("delivery_not_found")
                return record.id, record.status
        except DeliveryError:
            raise
        except SQLAlchemyError as error:
            logger.warning("mail delivery lookup failed (%s)", type(error).__name__)
            raise DeliveryError("database_unavailable") from error

    async def process_delivery(self, delivery_id: int) -> str:
        claimed = self._claim(delivery_id)
        if claimed is None:
            return self._status(delivery_id) or "missing"
        recipient, idempotency_key, brief = claimed
        if not recipient:
            self._finish(delivery_id, "failed", error_code="recipient_missing")
            return "failed"
        try:
            reference = await asyncio.to_thread(
                self.mailer.send_brief, brief, recipient, idempotency_key
            )
        except SMTPDeliveryFailure as error:
            self._record_send_failure(delivery_id, error)
            return self._status(delivery_id) or "failed"
        except Exception as error:  # noqa: BLE001 - SMTP adapter failures are normalized
            logger.warning(
                "mail send failed (delivery_id=%s, error_type=%s)",
                delivery_id,
                type(error).__name__,
            )
            self._record_send_failure(
                delivery_id, SMTPDeliveryFailure("smtp_adapter_error", "unknown")
            )
            return "unknown"
        self._finish(
            delivery_id,
            "submitted",
            submitted_at=utc_now(),
            provider_reference=reference[:255] if reference else None,
        )
        return "submitted"

    async def process_due_deliveries(self) -> None:
        now = utc_now()
        try:
            with self.session_factory() as session:
                delivery_ids = list(
                    session.scalars(
                        select(MailDeliveryRecord.id)
                        .where(
                            MailDeliveryRecord.status == "pending",
                            or_(
                                MailDeliveryRecord.next_attempt_at.is_(None),
                                MailDeliveryRecord.next_attempt_at <= now,
                            ),
                        )
                        .order_by(MailDeliveryRecord.created_at)
                        .limit(MAX_DUE_DELIVERIES_PER_SWEEP)
                    )
                )
        except SQLAlchemyError as error:
            logger.warning("due mail delivery lookup failed (%s)", type(error).__name__)
            return
        for delivery_id in delivery_ids:
            await self.process_delivery(delivery_id)

    def recover_inflight_as_unknown(self) -> None:
        try:
            with self.session_factory.begin() as session:
                session.execute(
                    update(MailDeliveryRecord)
                    .where(MailDeliveryRecord.status == "sending")
                    .values(status="unknown", last_error_code="smtp_result_unknown")
                )
        except SQLAlchemyError as error:
            logger.warning("mail in-flight recovery failed (%s)", type(error).__name__)

    def request_retry(self, brief_id: int, user_id: int = 1) -> int:
        try:
            with self.session_factory.begin() as session:
                record = session.scalar(
                    select(MailDeliveryRecord)
                    .join(BriefRecord, MailDeliveryRecord.brief_id == BriefRecord.id)
                    .join(TaskRunRecord, BriefRecord.run_id == TaskRunRecord.id)
                    .where(
                        MailDeliveryRecord.brief_id == brief_id,
                        TaskRunRecord.user_id == user_id,
                    )
                    .with_for_update()
                )
                if record is None:
                    raise DeliveryError("delivery_not_found")
                if record.status == "unknown":
                    raise DeliveryError("delivery_result_unknown")
                if record.status != "failed":
                    raise DeliveryError("delivery_not_retryable")
                if record.manual_retry_count >= MAX_MANUAL_RETRIES:
                    raise DeliveryError("manual_retry_limit")
                record.status = "pending"
                record.attempt_count = 0
                record.manual_retry_count += 1
                record.last_error_code = None
                record.next_attempt_at = utc_now()
                delivery_id = record.id
            return delivery_id
        except DeliveryError:
            raise
        except SQLAlchemyError as error:
            logger.warning("mail retry request failed (%s)", type(error).__name__)
            raise DeliveryError("database_unavailable") from error

    def _claim(self, delivery_id: int) -> tuple[str | None, str, BriefRead] | None:
        now = utc_now()
        try:
            with self.session_factory.begin() as session:
                delivery = session.scalar(
                    select(MailDeliveryRecord)
                    .where(MailDeliveryRecord.id == delivery_id)
                    .with_for_update()
                )
                if delivery is None or delivery.status != "pending":
                    return None
                brief_record = session.get(BriefRecord, delivery.brief_id)
                run = session.get(TaskRunRecord, brief_record.run_id) if brief_record else None
                profile = session.get(UserProfile, run.user_id) if run else None
                preferences = session.get(SubscriptionPreferences, run.user_id) if run else None
                if profile is None or profile.recipient_email != delivery.recipient_snapshot:
                    delivery.status = "skipped"
                    delivery.last_error_code = "recipient_changed"
                    return None
                if profile.mail_test_status != "succeeded":
                    delivery.status = "skipped"
                    delivery.last_error_code = "mail_not_verified"
                    return None
                if preferences is None or not preferences.enabled:
                    delivery.status = "skipped"
                    delivery.last_error_code = "subscription_disabled"
                    return None
                result = session.execute(
                    update(MailDeliveryRecord)
                    .where(
                        MailDeliveryRecord.id == delivery_id,
                        MailDeliveryRecord.status == "pending",
                        MailDeliveryRecord.attempt_count < self.settings.smtp_max_attempts,
                        or_(
                            MailDeliveryRecord.next_attempt_at.is_(None),
                            MailDeliveryRecord.next_attempt_at <= now,
                        ),
                    )
                    .values(
                        status="sending",
                        attempt_count=MailDeliveryRecord.attempt_count + 1,
                        last_attempt_at=now,
                        next_attempt_at=None,
                    )
                )
                if result.rowcount != 1:
                    return None
                delivery = session.get(MailDeliveryRecord, delivery_id)
                brief_record = session.get(BriefRecord, delivery.brief_id)
                content = BriefContent.model_validate(brief_record.content_json)
                brief = BriefRead(
                    id=brief_record.id,
                    run_id=brief_record.run_id,
                    run_status="completed" if content.items else "empty",
                    report_date=content.report_date,
                    generated_at=content.generated_at,
                    item_count=content.item_count,
                    items=content.items,
                    empty_reason=content.empty_reason,
                    warnings=content.warnings,
                )
                return delivery.recipient_snapshot, delivery.idempotency_key, brief
        except SQLAlchemyError as error:
            logger.warning("mail delivery claim failed (%s)", type(error).__name__)
            return None

    def _record_send_failure(self, delivery_id: int, error: SMTPDeliveryFailure) -> None:
        with self.session_factory() as session:
            record = session.get(MailDeliveryRecord, delivery_id)
            attempt_count = record.attempt_count if record is not None else 0
        if error.disposition == "unknown":
            self._finish(delivery_id, "unknown", error_code=error.code)
            return
        if error.disposition == "retry" and attempt_count < self.settings.smtp_max_attempts:
            delay = min(
                self.settings.smtp_retry_base_seconds * 2 ** (attempt_count - 1),
                900,
            )
            self._finish(
                delivery_id,
                "pending",
                error_code=error.code,
                next_attempt_at=utc_now() + timedelta(seconds=delay),
            )
            return
        self._finish(delivery_id, "failed", error_code=error.code)

    def _finish(self, delivery_id: int, status: str, **values) -> None:
        if "error_code" in values:
            values["last_error_code"] = values.pop("error_code")
        values["status"] = status
        try:
            with self.session_factory.begin() as session:
                session.execute(
                    update(MailDeliveryRecord)
                    .where(
                        MailDeliveryRecord.id == delivery_id,
                        MailDeliveryRecord.status == "sending",
                    )
                    .values(**values)
                )
        except SQLAlchemyError as error:
            logger.warning("mail delivery result update failed (%s)", type(error).__name__)

    def _status(self, delivery_id: int) -> str | None:
        try:
            with self.session_factory() as session:
                record = session.get(MailDeliveryRecord, delivery_id)
                return record.status if record is not None else None
        except SQLAlchemyError as error:
            logger.warning("mail delivery status lookup failed (%s)", type(error).__name__)
            return None
