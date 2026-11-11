"""Sample IPO data for demos/tests (IPO_SOURCE=fake)."""

from __future__ import annotations

from datetime import date, timedelta

from app.domain.models import Ipo


class FakeIpoSource:
    def __init__(self, ipos: list[Ipo] | None = None) -> None:
        today = date.today()
        self._ipos = ipos if ipos is not None else [
            Ipo(symbol="DEMOTECH", name="Demo Technologies Ltd", status="open",
                issue_start=today - timedelta(days=1), issue_end=today + timedelta(days=1),
                price_low=270, price_high=285, lot_size=52, issue_size="₹1,200 Cr", subscription_times=4.6),
            Ipo(symbol="SAMPLEFIN", name="Sample Finance Ltd", status="upcoming",
                issue_start=today + timedelta(days=4), issue_end=today + timedelta(days=6),
                price_low=95, price_high=100, lot_size=150, issue_size="₹650 Cr"),
            Ipo(symbol="TINYSME", name="Tiny SME Industries", category="SME", status="open",
                issue_start=today, issue_end=today + timedelta(days=2),
                price_low=60, price_high=62, lot_size=2000, issue_size="₹24 Cr", subscription_times=1.2),
        ]

    def list_ipos(self) -> list[Ipo]:
        return list(self._ipos)
