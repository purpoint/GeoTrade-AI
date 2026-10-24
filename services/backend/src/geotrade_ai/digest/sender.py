"""EmailSender implementations (P3-BE-04). Brevo's HTTP API in production (Railway blocks outbound SMTP),
SMTP for Mailpit in development, and a log sender that sends nothing (tests, or no provider set)."""

import logging
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from typing import Protocol

import httpx

from geotrade_ai.core.config import get_settings

log = logging.getLogger(__name__)


class SendError(Exception):
    def __init__(self, message: str, permanent: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent  # e.g. invalid address: no point retrying


class EmailSender(Protocol):
    name: str

    def send(self, to: str, subject: str, html: str, text: str, headers: dict[str, str]) -> str:
        """Returns the provider's message id. Raises SendError."""
        ...


class LogSender:
    name = "log"

    def __init__(self) -> None:
        self.outbox: list[dict[str, object]] = []

    def send(self, to: str, subject: str, html: str, text: str, headers: dict[str, str]) -> str:
        mid = f"log-{uuid.uuid4().hex[:12]}"
        self.outbox.append(
            {"to": to, "subject": subject, "html": html, "text": text, "headers": headers, "id": mid}
        )
        log.info("email not sent (EMAIL_PROVIDER=log)", extra={"extra": {"subject": subject, "id": mid}})
        return mid


class SmtpSender:
    name = "smtp"

    def send(self, to: str, subject: str, html: str, text: str, headers: dict[str, str]) -> str:
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = formataddr((s.email_from_name, s.email_from))
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = mid = make_msgid(domain="geotrade.local")
        for k, v in headers.items():
            msg[k] = v
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
        try:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                smtp.send_message(msg)
        except smtplib.SMTPRecipientsRefused as exc:
            raise SendError(str(exc), permanent=True) from exc
        except (OSError, smtplib.SMTPException) as exc:
            raise SendError(f"smtp: {exc}") from exc
        return mid


class BrevoSender:
    name = "brevo"
    URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(timeout=20, transport=transport)

    def send(self, to: str, subject: str, html: str, text: str, headers: dict[str, str]) -> str:
        s = get_settings()
        body = {
            "sender": {"name": s.email_from_name, "email": s.email_from},
            "to": [{"email": to}],
            "subject": subject,
            "htmlContent": html,
            "textContent": text,
            "headers": headers,
            "tags": ["daily-pulse"],
        }
        try:
            r = self._client.post(
                self.URL, json=body, headers={"api-key": s.brevo_api_key, "accept": "application/json"}
            )
        except httpx.HTTPError as exc:
            raise SendError(f"brevo transport: {exc}") from exc
        if r.status_code >= 400:
            raise SendError(
                f"brevo HTTP {r.status_code}: {r.text[:200]}", permanent=r.status_code in (400, 401, 403)
            )
        return str(r.json().get("messageId", ""))


def get_sender() -> EmailSender:
    provider = get_settings().email_provider
    if provider == "brevo":
        return BrevoSender()
    if provider == "smtp":
        return SmtpSender()
    return LogSender()
