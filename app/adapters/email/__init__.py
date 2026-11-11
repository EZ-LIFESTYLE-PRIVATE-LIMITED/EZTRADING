"""Email senders, picked from settings: SMTP if configured, else the console in development."""

from __future__ import annotations

from app.config import Settings
from app.domain.ports import EmailSenderPort


def create_email_sender(settings: Settings) -> EmailSenderPort:
    if settings.smtp_configured:
        from app.adapters.email.smtp import SmtpEmailSender

        return SmtpEmailSender(settings.smtp_host, settings.smtp_port, settings.smtp_user, settings.smtp_password,
                               settings.smtp_from, starttls=settings.smtp_starttls)
    from app.adapters.email.console import ConsoleEmailSender, NullEmailSender

    return NullEmailSender() if settings.is_production else ConsoleEmailSender()
