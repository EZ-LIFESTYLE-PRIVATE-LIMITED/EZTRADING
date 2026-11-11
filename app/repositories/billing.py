"""Premium subscriptions, coupons and billing orders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import BillingOrder, Coupon, CouponRedemption, Subscription


class SubscriptionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def latest_end(self, user_id: int) -> datetime | None:
        return self._db.scalar(select(func.max(Subscription.ends_at)).where(Subscription.user_id == user_id))

    def active(self, user_id: int, now: datetime) -> bool:
        stmt = select(Subscription.id).where(Subscription.user_id == user_id, Subscription.starts_at <= now,
                                             Subscription.ends_at > now).limit(1)
        return self._db.scalar(stmt) is not None

    def add(self, **fields: Any) -> Subscription:
        row = Subscription(**fields)
        self._db.add(row)
        self._db.commit()
        return row


class CouponRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(self, code: str) -> Coupon | None:
        return self._db.get(Coupon, code.strip().upper())

    def all(self) -> list[Coupon]:
        return list(self._db.scalars(select(Coupon).order_by(Coupon.created_at)))

    def upsert(self, code: str, **fields: Any) -> Coupon:
        row = self.get(code)
        if row is None:
            row = Coupon(code=code.strip().upper(), **fields)
            self._db.add(row)
        else:
            for key, value in fields.items():
                setattr(row, key, value)
        self._db.commit()
        return row

    def ensure(self, code: str, **fields: Any) -> None:
        """Create the coupon if missing; never overwrite an existing one (an admin may have changed it)."""
        if self.get(code) is None:
            try:
                self.upsert(code, **fields)
            except IntegrityError:  # another process seeded it first
                self._db.rollback()

    def redemptions(self, code: str) -> int:
        return self._db.scalar(select(func.count()).select_from(CouponRedemption)
                               .where(CouponRedemption.coupon_code == code)) or 0

    def redeemed_by(self, code: str, user_id: int) -> bool:
        stmt = select(CouponRedemption.id).where(CouponRedemption.coupon_code == code,
                                                 CouponRedemption.user_id == user_id)
        return self._db.scalar(stmt) is not None

    def redeem(self, code: str, user_id: int) -> bool:
        """Records a redemption; False if this user already used the coupon."""
        self._db.add(CouponRedemption(coupon_code=code, user_id=user_id))
        try:
            self._db.commit()
            return True
        except IntegrityError:
            self._db.rollback()
            return False


class BillingOrderRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def add(self, **fields: Any) -> BillingOrder:
        row = BillingOrder(**fields)
        self._db.add(row)
        self._db.commit()
        return row

    def get(self, order_id: str) -> BillingOrder | None:
        return self._db.get(BillingOrder, order_id)

    def mark(self, row: BillingOrder, status: str, provider_ref: str | None = None) -> BillingOrder:
        row.status = status
        if provider_ref:
            row.provider_ref = provider_ref
        self._db.commit()
        return row

    def transition(self, order_id: str, from_status: str, to_status: str, provider_ref: str | None) -> bool:
        """Atomically move an order between states; False if it wasn't in `from_status` any more."""
        values: dict[str, Any] = {"status": to_status}
        if provider_ref:
            values["provider_ref"] = provider_ref
        result = self._db.execute(update(BillingOrder)
                                  .where(BillingOrder.id == order_id, BillingOrder.status == from_status)
                                  .values(**values))
        self._db.commit()
        return result.rowcount == 1
