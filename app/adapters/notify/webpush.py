"""Browser Web Push (VAPID) sender."""

from __future__ import annotations

import json
import logging
from typing import Any

from pywebpush import WebPushException, webpush

from app.domain.models import Notification

log = logging.getLogger(__name__)
_GONE = {404, 410}


class WebPushSender:
    def __init__(self, private_key: str, subject: str) -> None:
        self._private_key = private_key
        self._claims = {"sub": subject}

    def send(self, subscription: dict[str, Any], notification: Notification) -> bool:
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(notification.model_dump()),
                vapid_private_key=self._private_key,
                vapid_claims=dict(self._claims),
                ttl=3600,
            )
            return True
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in _GONE:
                return False
            log.warning("Web push failed (%s): %s", status, exc)
            return True


class NullPushSender:
    def send(self, subscription: dict[str, Any], notification: Notification) -> bool:
        return True
