"""Application settings, loaded from environment / .env (12-factor style)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WATCHLIST = (
    "RELIANCE,HDFCBANK,ICICIBANK,INFY,TCS,BHARTIARTL,ITC,LT,SBIN,AXISBANK,"
    "KOTAKBANK,HINDUNILVR,BAJFINANCE,MARUTI,SUNPHARMA,TITAN,ULTRACEMCO,NTPC"
)

DEFAULT_MARKET_FEEDS = (
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms,"
    "https://www.moneycontrol.com/rss/marketreports.xml"
)


@dataclass(frozen=True)
class AdvisorOption:
    id: str          # "provider:model" or "rules"
    provider: str    # registry key; also the credential kind holding the API key
    model: str
    label: str


# Curated list shown in the advisor dropdown. Add a row to offer a new model.
ADVISOR_CATALOG: tuple[AdvisorOption, ...] = (
    AdvisorOption("gemini:gemini-3.6-flash", "gemini", "gemini-3.6-flash", "Gemini 3.6 Flash"),
    AdvisorOption("gemini:gemini-3.8-flash", "gemini", "gemini-3.8-flash", "Gemini 3.8 Flash"),
    AdvisorOption("claude:claude-opus-5-5", "claude", "claude-opus-5-5", "Claude Opus 5.5"),
    AdvisorOption("claude:claude-sonnet-5-5", "claude", "claude-sonnet-5-5", "Claude Sonnet 5.5"),
    AdvisorOption("rules", "rules", "", "Rules (offline, free)"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Runtime ------------------------------------------------------------
    env: str = Field("development", description="'development' or 'production'")
    public_base_url: str = "http://127.0.0.1:8000"
    database_url: str = "sqlite:///data/eztrading.db"
    data_dir: Path = Path("data")
    max_workers: int = 8

    # --- Security -----------------------------------------------------------
    session_secret: str = "dev-insecure-session-secret-change-me"
    app_encryption_key: str = ""  # Fernet key; required in production
    allowed_emails: str = ""      # optional comma-separated allowlist
    fixed_otp: str = "7891"       # outside production every email code is this (no inbox needed locally)

    # --- Google SSO ---------------------------------------------------------
    google_client_id: str = ""
    google_client_secret: str = ""

    # --- Broker -------------------------------------------------------------
    broker: str = Field("kite", description="'kite' (live, per-user keys) or 'fake' (demo data)")

    # --- AI advisor (server-wide defaults; users can override with their own keys)
    default_advisor: str = "gemini:gemini-3.6-flash"
    llm_effort: str = "high"  # Claude only
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    # --- Market data --------------------------------------------------------
    watchlist: str = DEFAULT_WATCHLIST
    market_index: str = "NIFTY 50"
    nse_holidays: str = ""  # comma-separated YYYY-MM-DD
    price_cache_ttl_seconds: int = 900
    intraday_cache_ttl_seconds: int = 60

    # --- News / IPO ---------------------------------------------------------
    market_news_feeds: str = DEFAULT_MARKET_FEEDS
    news_per_symbol: int = 4
    market_news_limit: int = 15
    news_timeout_seconds: float = 8.0
    ipo_source: str = Field("nse", description="'nse' or 'fake'")
    ipo_cache_ttl_seconds: int = 3600

    # --- Notifications ------------------------------------------------------
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""
    telegram_webhook_secret: str = ""
    telegram_polling: bool | None = None  # receive bot messages by polling; default: outside production only

    # --- Premium & billing ----------------------------------------------------
    premium_enforced: bool = True  # server AI keys need Premium (locally too; test payments succeed there)
    premium_plan: str = "premium_monthly"
    premium_price_inr: int = 199
    premium_period_days: int = 30
    payment_provider: str = "stub"
    payment_stub_allow_success: bool = False  # lets the stub "pay" in production (testing only)
    welcome_coupon: str = "FREE7"  # seeded at start-up; empty to skip
    welcome_coupon_days: int = 7

    # --- Email / password sign-in (optional) --------------------------------
    password_login: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    # --- Feature switches ---------------------------------------------------
    orders_enabled: bool = True  # False hides Execute and rejects every order request

    # --- Limits -------------------------------------------------------------
    manual_analyze_cooldown_seconds: int = 60

    @property
    def is_production(self) -> bool:
        return self.env.lower() == "production"

    @property
    def otp_override(self) -> str:
        """The fixed email code used outside production; never in production."""
        return "" if self.is_production else self.fixed_otp.strip()

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def premium_required(self) -> bool:
        return self.premium_enforced

    @property
    def new_user_advisor(self) -> str:
        """Free users can't use server keys where premium is enforced, so they start on Rules."""
        return "rules" if self.premium_required else self.default_advisor

    @property
    def payment_stub_can_succeed(self) -> bool:
        return not self.is_production or self.payment_stub_allow_success

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def password_login_enabled(self) -> bool:
        """Needs a way to deliver OTPs: real SMTP, or the console in development."""
        return self.password_login and (self.smtp_configured or not self.is_production)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_bot_username)

    @property
    def telegram_uses_polling(self) -> bool:
        if not self.telegram_enabled:
            return False
        return (not self.is_production) if self.telegram_polling is None else self.telegram_polling

    @property
    def watchlist_symbols(self) -> list[str]:
        return _split_csv(self.watchlist, upper=True)

    @property
    def market_feed_urls(self) -> list[str]:
        return _split_csv(self.market_news_feeds)

    @property
    def allowed_email_set(self) -> set[str]:
        return {e.lower() for e in _split_csv(self.allowed_emails)}

    @property
    def holiday_dates(self) -> set[date]:
        return {date.fromisoformat(d) for d in _split_csv(self.nse_holidays)}

    @property
    def server_api_keys(self) -> dict[str, str]:
        return {k: v for k, v in {"gemini": self.gemini_api_key, "claude": self.anthropic_api_key}.items() if v}

    @property
    def kite_redirect_url(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/auth/kite/callback"


def _split_csv(raw: str, upper: bool = False) -> list[str]:
    items = [part.strip() for part in raw.split(",") if part.strip()]
    return [i.upper() for i in items] if upper else items


def advisor_option(advisor_id: str) -> AdvisorOption | None:
    return next((o for o in ADVISOR_CATALOG if o.id == advisor_id), None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
