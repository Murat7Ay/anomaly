from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Iterable

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class EmailPayload:
    to_addresses: list[str]
    subject: str
    body: str


class SmtpEmailSender:
    def __init__(self) -> None:
        self._settings = get_settings()

    def send(self, payload: EmailPayload) -> None:
        smtp = self._settings.smtp()
        if not smtp.host:
            raise RuntimeError("smtp_not_configured")
        if not payload.to_addresses:
            raise RuntimeError("no_recipients")

        msg = EmailMessage()
        msg["From"] = smtp.from_addr
        msg["To"] = ", ".join(payload.to_addresses)
        msg["Subject"] = payload.subject
        msg.set_content(payload.body)

        with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
            if smtp.use_tls:
                server.starttls()
            if smtp.username and smtp.password:
                server.login(smtp.username, smtp.password)
            server.send_message(msg)


