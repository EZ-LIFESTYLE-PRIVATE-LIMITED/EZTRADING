"""Current and upcoming IPOs from NSE's public website JSON.

These endpoints are unofficial: NSE needs browser-like headers and cookies from
the homepage, field names occasionally change, and cloud IPs may be blocked.
Parsing is tolerant (several candidate keys per field) and results are cached.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import date, datetime
from typing import Any

import httpx

from app.domain.errors import EZTradingError
from app.domain.models import Ipo

log = logging.getLogger(__name__)

BASE = "https://www.nseindia.com"
CURRENT_URL = f"{BASE}/api/ipo-current-issue"
UPCOMING_URL = f"{BASE}/api/all-upcoming-issues?category=ipo"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36",
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Referer": f"{BASE}/market-data/all-upcoming-issues-ipo",
}


class NseIpoSource:
    def __init__(self, ttl_seconds: int = 3600, timeout: float = 10.0) -> None:
        self._ttl = ttl_seconds
        self._timeout = timeout
        self._cache: tuple[float, list[Ipo]] | None = None
        self._lock = threading.Lock()

    def list_ipos(self) -> list[Ipo]:
        with self._lock:
            if self._cache and time.monotonic() - self._cache[0] < self._ttl:
                return self._cache[1]
            ipos = self._fetch()  # errors are not cached, so the next request retries
            self._cache = (time.monotonic(), ipos)
            return ipos

    def _fetch(self) -> list[Ipo]:
        try:
            with httpx.Client(headers=_HEADERS, timeout=self._timeout, follow_redirects=True) as client:
                warmup = client.get(BASE)  # sets the cookies NSE's API expects
                current = client.get(CURRENT_URL).json()
                upcoming = client.get(UPCOMING_URL).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise EZTradingError(f"IPO data unavailable from NSE: {exc}") from exc
        ipos = merge_ipos(parse_issues(current, default_status="open"), parse_issues(upcoming, default_status="upcoming"))
        if not ipos and warmup.status_code >= 400:
            # Without cookies NSE answers with empty lists; don't present that as "no IPOs".
            raise EZTradingError(f"NSE blocked the request (HTTP {warmup.status_code}); IPO data is unavailable from this server right now")
        return ipos


def parse_issues(payload: Any, default_status: str) -> list[Ipo]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _first(row, "symbol", "Symbol")
        name = _first(row, "companyName", "company", "name") or symbol
        if not symbol:
            continue
        low, high = _price_band(_first(row, "issuePrice", "priceBand", "priceRange"))
        series = str(_first(row, "series", "category", "issueType") or "").upper()
        start, end = _date(_first(row, "issueStartDate", "startDate")), _date(_first(row, "issueEndDate", "endDate"))
        result.append(Ipo(
            symbol=str(symbol).strip().upper(),
            name=str(name).strip(),
            category="SME" if "SME" in series or series == "ST" else "Mainboard",
            status=_status(_first(row, "status"), start, end, default_status),
            issue_start=start,
            issue_end=end,
            price_low=low,
            price_high=high,
            lot_size=_int(_first(row, "lotSize", "minBidQuantity", "marketLot", "minimumBidQty")),
            issue_size=_str(_first(row, "issueSize", "noOfSharesOffered")),
            subscription_times=_float(_first(row, "noOfTime", "subscriptionTimes", "noOfTimesSubscribed")),
        ))
    return result


def merge_ipos(*groups: list[Ipo]) -> list[Ipo]:
    seen: dict[str, Ipo] = {}
    for group in groups:
        for ipo in group:
            seen.setdefault(ipo.symbol, ipo)
    order = {"open": 0, "upcoming": 1, "closed": 2}
    return sorted(seen.values(), key=lambda i: (order.get(i.status, 3), i.issue_start or date.max))


def _first(row: dict, *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "-"):
            return value
    return None


def _price_band(value: Any) -> tuple[float | None, float | None]:
    if value is None:
        return None, None
    numbers = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", str(value))]
    if not numbers:
        return None, None
    return min(numbers), max(numbers)


def _date(value: Any) -> date | None:
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def _status(raw: Any, start: date | None, end: date | None, default: str) -> str:
    text = str(raw or "").lower()
    if "active" in text or "open" in text:
        return "open"
    if "close" in text:
        return "closed"
    if "forth" in text or "upcoming" in text:
        return "upcoming"
    today = date.today()
    if start and end:
        if start <= today <= end:
            return "open"
        if today < start:
            return "upcoming"
        return "closed"
    return default


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return round(float(str(value).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    return None if value is None else str(value)
