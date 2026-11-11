"""Auto-analysis worker. Run exactly one instance: python -m app.worker

`python -m app.worker --check` is the container healthcheck: it exits 0 only if
a tick completed successfully within the last few minutes.
"""

from __future__ import annotations

import logging
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.config import get_settings
from app.container import build_app_container

TICK_SECONDS = 60
HEARTBEAT_FILE = Path(tempfile.gettempdir()) / "eztrading-worker.heartbeat"
HEARTBEAT_MAX_AGE = TICK_SECONDS * 3
log = logging.getLogger("eztrading.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    runner = build_app_container(get_settings()).auto_runner()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    log.info("Worker started; ticking every %ss", TICK_SECONDS)
    while not stop.is_set():
        try:
            ran = runner.tick()
            HEARTBEAT_FILE.touch()  # only successful ticks count as healthy
            log.info("Tick: ran auto-analysis for %d user(s)", len(ran))
        except Exception:
            log.exception("Tick failed")
        stop.wait(TICK_SECONDS)
    log.info("Worker stopped")


def is_healthy(now: float | None = None) -> bool:
    try:
        age = (now or time.time()) - HEARTBEAT_FILE.stat().st_mtime
    except FileNotFoundError:
        return False
    return age <= HEARTBEAT_MAX_AGE


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(0 if is_healthy() else 1)
    main()
