"""Receive Telegram bot messages by long polling, for servers Telegram can't reach (your PC).

Production uses the webhook (/telegram/webhook) instead. A bot can't do both at once: while a webhook
is set, polling is refused, so give local development its own bot (or delete the webhook).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

import httpx

log = logging.getLogger("eztrading.telegram")

POLL_SECONDS = 25
RETRY_SECONDS = 5


class TelegramPoller:
    def __init__(self, bot_token: str, handle: Callable[[dict[str, Any]], None]) -> None:
        self._api = f"https://api.telegram.org/bot{bot_token}"
        self._handle = handle
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        with httpx.Client(timeout=POLL_SECONDS + 10) as client:
            if not self._webhook_clear(client):
                return
            log.info("Telegram: polling for messages (local mode)")
            offset = 0
            while not self._stop.is_set():
                try:
                    r = client.get(f"{self._api}/getUpdates", params={
                        "offset": offset, "timeout": POLL_SECONDS, "allowed_updates": '["message"]'})
                    r.raise_for_status()
                    for update in r.json().get("result", []):
                        offset = update["update_id"] + 1
                        self._dispatch(update)
                except httpx.HTTPError as exc:
                    log.warning("Telegram polling failed (%s); retrying in %ss", exc.__class__.__name__,
                                RETRY_SECONDS)
                    self._stop.wait(RETRY_SECONDS)

    def _webhook_clear(self, client: httpx.Client) -> bool:
        try:
            url = client.get(f"{self._api}/getWebhookInfo").json().get("result", {}).get("url")
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Telegram: couldn't check the bot's webhook (%s); polling anyway", exc.__class__.__name__)
            return True
        if url:
            log.error("Telegram: this bot has a webhook set (%s), so local polling is off and linking won't work "
                      "here. Use a separate bot for local development, or delete the webhook.", url)
            return False
        return True

    def _dispatch(self, update: dict[str, Any]) -> None:
        try:
            self._handle(update)
        except Exception:  # noqa: BLE001 - one bad update must not stop the loop
            log.exception("Telegram: failed to handle an update")
