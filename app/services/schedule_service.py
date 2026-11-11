"""Per-user auto-analysis schedules ("reminders"): each runs one trading style on its own interval."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from pydantic import BaseModel, Field

from app.db.models import AutoSchedule
from app.domain.errors import NotFoundError, ValidationError
from app.repositories.users import ScheduleRepository
from app.services.styles import get_style

MAX_INTERVAL_MIN = 24 * 60
MAX_SCHEDULES = 10


class ScheduleView(BaseModel):
    id: int
    style: str
    interval_min: int
    enabled: bool
    next_run_at: datetime | None


class ScheduleInput(BaseModel):
    style: str
    interval_min: int = Field(ge=1)
    enabled: bool = True


class SchedulePatch(BaseModel):
    style: str | None = None
    interval_min: int | None = Field(default=None, ge=1)
    enabled: bool | None = None


class ScheduleService:
    def __init__(self, user_id: int, repo: ScheduleRepository, clock: Callable[[], datetime]) -> None:
        self._user_id = user_id
        self._repo = repo
        self._clock = clock

    def list(self) -> list[ScheduleView]:
        return [_view(r) for r in self._repo.list_for_user(self._user_id)]

    def create(self, data: ScheduleInput) -> ScheduleView:
        if len(self._repo.list_for_user(self._user_id)) >= MAX_SCHEDULES:
            raise ValidationError(f"You can have at most {MAX_SCHEDULES} auto-analysis schedules")
        _check(data.style, data.interval_min)
        self._check_unique(data.style, data.interval_min)
        row = self._repo.add(self._user_id, style=data.style, interval_min=data.interval_min, enabled=data.enabled,
                             next_run_at=self._clock() if data.enabled else None)
        return _view(row)

    def update(self, schedule_id: int, patch: SchedulePatch) -> ScheduleView:
        row = self._get(schedule_id)
        changes = patch.model_dump(exclude_none=True)
        style, interval = changes.get("style", row.style), changes.get("interval_min", row.interval_min)
        _check(style, interval)
        self._check_unique(style, interval, exclude_id=row.id)
        if changes.get("enabled") and not row.enabled:
            changes["next_run_at"] = self._clock()  # run at the next tick
        return _view(self._repo.update(row, **changes))

    def delete(self, schedule_id: int) -> None:
        self._repo.delete(self._get(schedule_id))

    def _check_unique(self, style_key: str, interval_min: int, exclude_id: int | None = None) -> None:
        for other in self._repo.list_for_user(self._user_id):
            if other.id != exclude_id and other.style == style_key and other.interval_min == interval_min:
                raise ValidationError(
                    f"You already have a {get_style(style_key).label} schedule every {interval_min} min")

    def _get(self, schedule_id: int) -> AutoSchedule:
        row = self._repo.get(self._user_id, schedule_id)
        if row is None:
            raise NotFoundError("Schedule not found")
        return row


def _check(style_key: str, interval_min: int) -> None:
    style = get_style(style_key)
    if not style.min_auto_interval_min <= interval_min <= MAX_INTERVAL_MIN:
        raise ValidationError(
            f"Auto-analysis interval for {style.label} must be {style.min_auto_interval_min}-{MAX_INTERVAL_MIN} minutes")


def _view(row: AutoSchedule) -> ScheduleView:
    return ScheduleView(id=row.id, style=row.style, interval_min=row.interval_min, enabled=row.enabled,
                        next_run_at=row.next_run_at)
