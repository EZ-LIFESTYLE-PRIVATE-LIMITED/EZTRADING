"""Telegram Bot API messenger."""

from __future__ import annotations

import logging

import httpx

from app.domain.models import Notification

log = logging.getLogger(__name__)


class TelegramMessenger:
    def __init__(self, bot_token: str, base_url: str, timeout: float = 10.0) -> None:
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout)

    def send(self, chat_id: str, notification: Notification) -> None:
        link = notification.url if notification.url.startswith("http") else f"{self._base_url}{notification.url}"
        text = f"{notification.title}\n\n{notification.body}\n\n{link}"
        try:
            self._client.post(self._url, json={"chat_id": chat_id, "text": text,
                                               "disable_web_page_preview": True}).raise_for_status()
        except httpx.HTTPError as exc:  # str(exc) contains the URL, which holds the bot token: don't log it
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            log.warning("Telegram send failed: %s%s", exc.__class__.__name__, f" (HTTP {status})" if status else "")


class NullMessenger:
    def send(self, chat_id: str, notification: Notification) -> None:
        return None
