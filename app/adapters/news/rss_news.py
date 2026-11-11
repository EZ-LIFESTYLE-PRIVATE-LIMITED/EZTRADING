"""News from free RSS feeds: Google News search + market-wide feeds."""

from __future__ import annotations

import logging
from datetime import datetime
from time import mktime
from urllib.parse import quote_plus

import feedparser
import httpx

from app.domain.models import NewsItem

log = logging.getLogger(__name__)

GOOGLE_NEWS_URL = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; EZTrading/1.0)"}


class RssNews:
    def __init__(self, market_feeds: list[str], timeout: float = 8.0) -> None:
        self._market_feeds = market_feeds
        self._client = httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True)

    def search(self, query: str, limit: int) -> list[NewsItem]:
        return self._fetch(GOOGLE_NEWS_URL.format(query=quote_plus(f"{query} when:7d")))[:limit]

    def symbol_news(self, symbol: str, limit: int) -> list[NewsItem]:
        return self.search(f'"{symbol}" share NSE', limit)

    def market_news(self, limit: int) -> list[NewsItem]:
        items: list[NewsItem] = []
        for url in self._market_feeds:
            items.extend(self._fetch(url))
        items = _dedupe(items)
        items.sort(key=lambda n: n.published or datetime.min, reverse=True)
        return items[:limit]

    def _fetch(self, url: str) -> list[NewsItem]:
        try:
            resp = self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            log.warning("News feed failed (%s): %s", url, exc)
            return []
        feed = feedparser.parse(resp.content)
        return [_to_item(e, feed.feed.get("title", "")) for e in feed.entries if e.get("title")]


def _to_item(entry, default_source: str) -> NewsItem:
    published = None
    if entry.get("published_parsed"):
        published = datetime.fromtimestamp(mktime(entry.published_parsed))
    source = entry.get("source", {}).get("title") if entry.get("source") else default_source
    return NewsItem(title=entry.title.strip(), link=entry.get("link", ""), source=source or "", published=published)


def _dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen: set[str] = set()
    unique = []
    for item in items:
        key = item.title.lower()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


class NullNews:
    """No-op news source for tests/offline mode."""

    def search(self, query: str, limit: int) -> list[NewsItem]:
        return []

    def symbol_news(self, symbol: str, limit: int) -> list[NewsItem]:
        return []

    def market_news(self, limit: int) -> list[NewsItem]:
        return []
