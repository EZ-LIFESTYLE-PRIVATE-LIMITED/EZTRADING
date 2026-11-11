"""Links a Telegram chat to a user via a one-time /start code."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.domain.models import Notification
from app.domain.ports import MessengerPort
from app.repositories.notifications import TelegramLinkRepository
from app.repositories.users import SettingsRepository

log = logging.getLogger("eztrading.telegram")
_CODE = re.compile(r"[A-Za-z0-9_-]{16,64}")  # secrets.token_urlsafe(16) -> 22 chars


class TelegramLinker:
    def __init__(self, links: TelegramLinkRepository, settings_repo: SettingsRepository,
                 messenger: MessengerPort, bot_username: str) -> None:
        self._links = links
        self._settings = settings_repo
        self._messenger = messenger
        self._bot = bot_username

    def link_url(self, user_id: int) -> str:
        return f"https://t.me/{self._bot}?start={self._links.create(user_id)}"

    def handle_update(self, update: dict[str, Any]) -> bool:
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if not chat_id:
            return False
        code = self._extract_code(str(message.get("text") or ""))
        if code is None:
            log.info("Telegram: message without a link code from chat %s", chat_id)
            self._messenger.send(str(chat_id), Notification(
                title="EZTrading", body="To link this chat, open Settings in EZTrading, click Connect Telegram "
                                        "and send the /start code it shows (or open its link)."))
            return False
        user_id = self._links.consume(code)
        if user_id is None:
            log.info("Telegram: unknown or expired link code from chat %s", chat_id)
            self._messenger.send(str(chat_id), Notification(
                title="EZTrading", body="This link has expired. Open Settings in EZTrading and click Connect Telegram again."))
            return False
        self._settings.update(user_id, telegram_chat_id=str(chat_id), telegram_enabled=True)
        self._messenger.send(str(chat_id), Notification(
            title="EZTrading linked", body="You'll get a message here when an action needs your attention."))
        log.info("Telegram: linked user %s", user_id)
        return True

    @staticmethod
    def _extract_code(text: str) -> str | None:
        """Accepts "/start CODE", "/start@bot CODE" or a bare pasted CODE; None for a plain /start or chatter."""
        parts = text.strip().split()
        if not parts:
            return None
        if parts[0].startswith("/start"):
            return parts[1] if len(parts) >= 2 else None
        return parts[0] if len(parts) == 1 and _CODE.fullmatch(parts[0]) else None
