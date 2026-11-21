import hashlib
import smtplib
import ssl
from email.message import EmailMessage
from typing import Literal

from app.core.config import Settings
from app.schemas.brief import BriefRead

DeliveryDisposition = Literal["retry", "failed", "unknown"]


class SMTPDeliveryFailure(RuntimeError):
    def __init__(self, code: str, disposition: DeliveryDisposition) -> None:
        super().__init__(code)
        self.code = code
        self.disposition = disposition


class SMTPMailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def is_configured(self) -> bool:
        settings = self.settings
        if not all(
            (
                settings.smtp_host,
                settings.smtp_port,
                settings.smtp_security,
                settings.smtp_from_email,
            )
        ):
            return False
        if "example.com" in (settings.smtp_host or "").casefold():
            return False
        has_username = bool(settings.smtp_username and settings.smtp_username.strip())
        has_password = bool(
            settings.smtp_password and settings.smtp_password.get_secret_value().strip()
        )
        return has_username == has_password and not (
            has_username and settings.smtp_security == "none"
        )

    def send_brief(self, brief: BriefRead, recipient: str, idempotency_key: str) -> None:
        if not brief.items:
            raise SMTPDeliveryFailure("empty_brief_not_sendable", "failed")
        subject = f"每日 AI 新闻简报 | {brief.report_date.isoformat()}"
        lines = [f"{brief.report_date.isoformat()} 每日 AI 新闻简报", ""]
        for index, item in enumerate(brief.items, start=1):
            published = item.published_at_raw or "发布时间未提供/无法确认"
            lines.extend(
                (
                    f"{index}. {item.title}",
                    item.summary,
                    f"关注理由：{item.relevance_reason}",
                    f"来源：{item.source_name}",
                    f"发布时间：{published}",
                    f"原文：{item.url}",
                    "",
                )
            )
        return self.send_message(recipient, subject, "\n".join(lines), idempotency_key)

    def send_test(self, recipient: str, idempotency_key: str) -> None:
        return self.send_message(
            recipient,
            "每日 AI 新闻助手邮件配置测试",
            "这是一封邮件配置测试。只有在本人邮箱中实际收到后，才确认启用每日推送。",
            idempotency_key,
        )

    def send_message(
        self,
        recipient: str,
        subject: str,
        body: str,
        idempotency_key: str,
    ) -> None:
        if not self.is_configured:
            raise SMTPDeliveryFailure("smtp_not_configured", "failed")
        message_id = self._message_id(idempotency_key)
        message = EmailMessage()
        message["From"] = str(self.settings.smtp_from_email)
        message["To"] = recipient
        message["Subject"] = subject
        message["Message-ID"] = message_id
        message.set_content(body)

        client = None
        try:
            if self.settings.smtp_security == "ssl":
                client = smtplib.SMTP_SSL(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                    context=ssl.create_default_context(),
                )
            else:
                client = smtplib.SMTP(
                    self.settings.smtp_host,
                    self.settings.smtp_port,
                    timeout=self.settings.smtp_timeout_seconds,
                )
            client.ehlo()
            if self.settings.smtp_security == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if self.settings.smtp_username:
                password = self.settings.smtp_password.get_secret_value()
                client.login(self.settings.smtp_username, password)
        except smtplib.SMTPAuthenticationError as error:
            self._close(client)
            raise SMTPDeliveryFailure("smtp_auth_rejected", "failed") from error
        except smtplib.SMTPResponseException as error:
            self._close(client)
            raise self._response_failure(error) from error
        except (smtplib.SMTPException, OSError) as error:
            self._close(client)
            raise SMTPDeliveryFailure("smtp_connection_failed", "retry") from error

        try:
            refused = client.send_message(message, to_addrs=[recipient])
            if refused:
                response_codes = [response[0] for response in refused.values()]
                if any(400 <= code < 500 for code in response_codes):
                    raise SMTPDeliveryFailure("smtp_temporary_rejection", "retry")
                raise SMTPDeliveryFailure("smtp_recipient_rejected", "failed")
            return
        except SMTPDeliveryFailure:
            raise
        except smtplib.SMTPRecipientsRefused as error:
            raise SMTPDeliveryFailure("smtp_recipient_rejected", "failed") from error
        except smtplib.SMTPResponseException as error:
            raise self._response_failure(error) from error
        except (smtplib.SMTPServerDisconnected, OSError) as error:
            raise SMTPDeliveryFailure("smtp_result_unknown", "unknown") from error
        except smtplib.SMTPException as error:
            raise SMTPDeliveryFailure("smtp_send_failed", "unknown") from error
        finally:
            self._close(client)

    @staticmethod
    def _message_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"<{digest}@daily-ai-news.local>"

    @staticmethod
    def _response_failure(error: smtplib.SMTPResponseException) -> SMTPDeliveryFailure:
        if 400 <= error.smtp_code < 500:
            return SMTPDeliveryFailure("smtp_temporary_rejection", "retry")
        return SMTPDeliveryFailure("smtp_permanent_rejection", "failed")

    @staticmethod
    def _close(client) -> None:
        if client is None:
            return
        try:
            client.quit()
        except (smtplib.SMTPException, OSError):
            try:
                client.close()
            except OSError:
                pass
