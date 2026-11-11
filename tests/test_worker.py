import os

from app import worker


def test_worker_health_depends_on_fresh_heartbeat(tmp_path, monkeypatch):
    beat = tmp_path / "beat"
    monkeypatch.setattr(worker, "HEARTBEAT_FILE", beat)
    assert not worker.is_healthy()

    beat.touch()
    now = beat.stat().st_mtime
    assert worker.is_healthy(now=now + worker.HEARTBEAT_MAX_AGE - 1)
    assert not worker.is_healthy(now=now + worker.HEARTBEAT_MAX_AGE + 1)

    os.utime(beat, (now - 10_000, now - 10_000))
    assert not worker.is_healthy(now=now)
