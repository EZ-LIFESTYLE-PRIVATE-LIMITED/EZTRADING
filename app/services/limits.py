"""Per-user, process-local guard: one analysis at a time plus a cooldown between manual runs."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

from app.domain.errors import RateLimitedError


class AnalyzeLimiter:
    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown = cooldown_seconds
        self._busy: set[int] = set()
        self._last: dict[int, float] = {}
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self, user_id: int, enforce_cooldown: bool = True) -> Iterator[None]:
        now = time.monotonic()
        with self._lock:
            if user_id in self._busy:
                raise RateLimitedError("An analysis is already running for your account")
            wait = self._cooldown - (now - self._last.get(user_id, -1e9))
            if enforce_cooldown and wait > 0:
                raise RateLimitedError(f"Please wait {int(wait) + 1}s before analysing again")
            self._busy.add(user_id)
        try:
            yield
        finally:
            with self._lock:
                self._busy.discard(user_id)
                self._last[user_id] = time.monotonic()
