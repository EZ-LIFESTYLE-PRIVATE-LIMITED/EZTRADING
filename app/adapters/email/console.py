"""Development email: print to the server log instead of sending."""

from __future__ import annotations

import logging

from app.domain.models import EmailMessage

log = logging.getLogger("eztrading.email")


class ConsoleEmailSender:
    def send(self, message: EmailMessage) -> None:
        log.warning("EMAIL (dev, not sent) to %s | %s\n%s", message.to, message.subject, message.text)


class NullEmailSender:
    def send(self, message: EmailMessage) -> None:
        log.error("Email not sent (SMTP is not configured): %s to %s", message.subject, message.to)
