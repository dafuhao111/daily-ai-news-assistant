import asyncio
import logging
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.delivery.smtp import SMTPDeliveryFailure, SMTPMailer
from app.models.profile import UserProfile, utc_now
from app.schemas.mail import MailTestRead

logger = logging.getLogger(__name__)


class MailTestError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MailTestService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        mailer: SMTPMailer,
    ) -> None:
        self.session_factory = session_factory
        self.mailer = mailer

    async def submit_test(self, user_id: int = 1) -> MailTestRead:
        with self.session_factory.begin() as session:
            profile = session.get(UserProfile, user_id)
            if profile is None:
                raise MailTestError("profile_not_configured")
            if not profile.recipient_email:
                raise MailTestError("recipient_not_configured")
            recipient = profile.recipient_email
            profile.mail_test_status = "pending"
            profile.mail_tested_at = None

        try:
            await asyncio.to_thread(
                self.mailer.send_test,
                recipient,
                f"mail-test:{user_id}:{uuid4()}",
            )
        except SMTPDeliveryFailure as error:
            self._record_result(user_id, recipient, succeeded=False)
            return MailTestRead(status="failed", error_code=error.code)
        except Exception as error:  # noqa: BLE001 - keep SMTP internals out of API
            logger.warning("mail test failed (error_type=%s)", type(error).__name__)
            self._record_result(user_id, recipient, succeeded=False)
            return MailTestRead(status="failed", error_code="smtp_adapter_error")

        self._record_result(user_id, recipient, succeeded=True)
        return MailTestRead(status="pending")

    def confirm_received(self, user_id: int = 1) -> MailTestRead:
        try:
            with self.session_factory.begin() as session:
                profile = session.get(UserProfile, user_id)
                if profile is None or not profile.recipient_email:
                    raise MailTestError("recipient_not_configured")
                if profile.mail_test_status != "pending" or profile.mail_tested_at is None:
                    raise MailTestError("mail_test_not_pending")
                profile.mail_test_status = "succeeded"
        except MailTestError:
            raise
        except SQLAlchemyError as error:
            logger.warning("mail test confirmation failed (%s)", type(error).__name__)
            raise MailTestError("database_unavailable") from error
        return MailTestRead(status="succeeded")

    def _record_result(self, user_id: int, recipient: str, *, succeeded: bool) -> None:
        try:
            with self.session_factory.begin() as session:
                profile = session.get(UserProfile, user_id)
                if profile is None or profile.recipient_email != recipient:
                    return
                profile.mail_tested_at = utc_now()
                if not succeeded:
                    profile.mail_test_status = "failed"
        except SQLAlchemyError as error:
            logger.warning("mail test status update failed (%s)", type(error).__name__)
