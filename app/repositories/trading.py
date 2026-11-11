"""Plans, per-suggestion actions and orders for one user."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import OrderRow, PlanRow, SuggestionAction
from app.domain.errors import ConflictError
from app.domain.models import AllocationPlan, OrderRecord, SuggestionStatus

_FINAL = {SuggestionStatus.EXECUTED.value, SuggestionStatus.IGNORED.value, SuggestionStatus.EXECUTING.value}


class PlanRepository:
    def __init__(self, db: Session, user_id: int) -> None:
        self._db = db
        self._user_id = user_id

    def save(self, plan: AllocationPlan, fingerprint: str, created_at: datetime | None = None) -> None:
        self._db.add(PlanRow(
            id=plan.id, user_id=self._user_id, style=plan.style, advisor=plan.advisor,
            payload=plan.model_dump(mode="json"), fingerprint=fingerprint, created_at=created_at or utcnow(),
        ))
        self._db.commit()

    def get(self, plan_id: str) -> AllocationPlan | None:
        row = self._db.get(PlanRow, plan_id)
        if row is None or row.user_id != self._user_id:
            return None
        return self._with_statuses(row)

    def latest(self) -> AllocationPlan | None:
        row = self._db.scalar(
            select(PlanRow).where(PlanRow.user_id == self._user_id, PlanRow.dismissed.is_(False))
            .order_by(PlanRow.created_at.desc()).limit(1)
        )
        return self._with_statuses(row) if row else None

    def created_at(self, plan_id: str):
        row = self._db.get(PlanRow, plan_id)
        return row.created_at if row and row.user_id == self._user_id else None

    def dismiss(self, plan_id: str) -> bool:
        row = self._db.get(PlanRow, plan_id)
        if row is None or row.user_id != self._user_id:
            return False
        row.dismissed = True
        self._db.commit()
        return True

    def _with_statuses(self, row: PlanRow) -> AllocationPlan:
        plan = AllocationPlan.model_validate(row.payload)
        statuses = SuggestionActionRepository(self._db).statuses(row.id)
        for s in plan.suggestions:
            s.status = SuggestionStatus(statuses.get(s.id, SuggestionStatus.PENDING.value))
        return plan


class SuggestionActionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def statuses(self, plan_id: str) -> dict[str, str]:
        rows = self._db.scalars(select(SuggestionAction).where(SuggestionAction.plan_id == plan_id))
        return {r.suggestion_id: r.status for r in rows}

    def claim(self, plan_id: str, suggestion_id: str, status: SuggestionStatus) -> None:
        """Atomically move a suggestion out of pending/failed. Raises ConflictError otherwise."""
        row = self._db.scalar(select(SuggestionAction).where(
            SuggestionAction.plan_id == plan_id, SuggestionAction.suggestion_id == suggestion_id
        ).with_for_update())
        if row is not None and row.status in _FINAL:
            raise ConflictError(f"Suggestion already {row.status}")
        if row is None:
            self._db.add(SuggestionAction(plan_id=plan_id, suggestion_id=suggestion_id, status=status.value))
        else:
            row.status = status.value
        try:
            self._db.commit()
        except Exception as exc:  # unique constraint lost a race
            self._db.rollback()
            raise ConflictError("Suggestion is already being processed") from exc

    def set(self, plan_id: str, suggestion_id: str, status: SuggestionStatus) -> None:
        row = self._db.scalar(select(SuggestionAction).where(
            SuggestionAction.plan_id == plan_id, SuggestionAction.suggestion_id == suggestion_id
        ))
        if row is not None:
            row.status = status.value
            self._db.commit()


class OrderRepository:
    def __init__(self, db: Session, user_id: int) -> None:
        self._db = db
        self._user_id = user_id

    def add(self, **fields) -> OrderRow:
        row = OrderRow(user_id=self._user_id, created_at=utcnow(), **fields)
        self._db.add(row)
        self._db.commit()
        return row

    def update(self, row: OrderRow, **fields) -> OrderRow:
        for key, value in fields.items():
            setattr(row, key, value)
        self._db.commit()
        return row

    def get_row(self, order_id: int) -> OrderRow | None:
        row = self._db.get(OrderRow, order_id)
        return row if row and row.user_id == self._user_id else None

    def list(self, limit: int = 50) -> list[OrderRecord]:
        rows = self._db.scalars(
            select(OrderRow).where(OrderRow.user_id == self._user_id).order_by(OrderRow.created_at.desc()).limit(limit)
        )
        return [to_record(r) for r in rows]

    def spent_on_plan(self, plan_id: str, intraday: bool) -> float:
        """Notional already committed by live orders on this plan (MIS orders if intraday, else CNC buys)."""
        scope = (OrderRow.product == "MIS") if intraday else ((OrderRow.product == "CNC") & (OrderRow.side == "BUY"))
        total = self._db.scalar(select(func.coalesce(func.sum(OrderRow.est_amount), 0.0)).where(
            OrderRow.user_id == self._user_id, OrderRow.plan_id == plan_id,
            OrderRow.status.not_in(["FAILED", "REJECTED", "CANCELLED"]), scope,
        ))
        return float(total or 0.0)


def to_record(row: OrderRow) -> OrderRecord:
    return OrderRecord(
        id=row.id, plan_id=row.plan_id, suggestion_id=row.suggestion_id, symbol=row.symbol, side=row.side,
        quantity=row.quantity, product=row.product, order_type=row.order_type, price=row.price,
        est_amount=row.est_amount, broker_order_id=row.broker_order_id, status=row.status, error=row.error,
        created_at=row.created_at,
    )
