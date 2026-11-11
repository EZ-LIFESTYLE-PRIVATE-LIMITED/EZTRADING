"""Plain SMTP (works with Gmail/Google Workspace app passwords, Zoho, SES, Resend, Brevo...)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage as MimeMessage

from app.domain.models import EmailMessage

TIMEOUT_SECONDS = 15


class SmtpEmailSender:
    def __init__(self, host: str, port: int, user: str, password: str, sender: str, starttls: bool = True) -> None:
        self._host, self._port, self._user, self._password = host, port, user, password
        self._sender, self._starttls = sender, starttls

    def send(self, message: EmailMessage) -> None:
        mime = MimeMessage()
        mime["From"], mime["To"], mime["Subject"] = self._sender, message.to, message.subject
        mime.set_content(message.text)
        context = ssl.create_default_context()
        if self._port == 465:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=TIMEOUT_SECONDS, context=context) as smtp:
                self._deliver(smtp, mime)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=TIMEOUT_SECONDS) as smtp:
                if self._starttls:
                    smtp.starttls(context=context)
                self._deliver(smtp, mime)

    def _deliver(self, smtp: smtplib.SMTP, mime: MimeMessage) -> None:
        if self._user:
            smtp.login(self._user, self._password)
        smtp.send_message(mime)
