"""User settings, stored credentials, wallet and portfolio."""

from __future__ import annotations

import logging

from pydantic import BaseModel

from app.config import Settings
from app.domain.errors import EZTradingError, ValidationError
from app.domain.models import PortfolioSummary
from app.domain.ports import BrokerPort, TokenStore
from app.repositories.users import CredentialRepository, SettingsRepository, WalletRepository
from app.security.crypto import mask
from app.services.advisor_resolver import AdvisorResolver
from app.services.styles import STYLES, get_style

log = logging.getLogger(__name__)

AI_KINDS = {"gemini", "claude"}
CREDENTIAL_KINDS = {"kite", *AI_KINDS}


class SettingsView(BaseModel):
    advisor_id: str
    default_style: str
    push_enabled: bool
    telegram_enabled: bool
    telegram_linked: bool
    credentials: dict[str, str | None]
    server_keys: list[str]
    server_keys_allowed: bool  # False for free users where premium is enforced
    kite_redirect_url: str


class SettingsUpdate(BaseModel):
    advisor_id: str | None = None
    default_style: str | None = None
    push_enabled: bool | None = None
    telegram_enabled: bool | None = None
    unlink_telegram: bool | None = None


class CredentialInput(BaseModel):
    api_key: str
    api_secret: str | None = None


class SettingsService:
    def __init__(
        self,
        user_id: int,
        app_settings: Settings,
        settings_repo: SettingsRepository,
        credentials: CredentialRepository,
        kite_tokens: TokenStore,
        resolver: AdvisorResolver,
    ) -> None:
        self._user_id = user_id
        self._app = app_settings
        self._repo = settings_repo
        self._credentials = credentials
        self._kite_tokens = kite_tokens
        self._resolver = resolver

    def view(self) -> SettingsView:
        row = self._repo.get(self._user_id)
        hints = self._credentials.hints()
        return SettingsView(
            advisor_id=row.advisor_id,
            default_style=row.default_style,
            push_enabled=row.push_enabled,
            telegram_enabled=row.telegram_enabled,
            telegram_linked=bool(row.telegram_chat_id),
            credentials={kind: hints.get(kind) for kind in sorted(CREDENTIAL_KINDS)},
            server_keys=sorted(self._app.server_api_keys),
            server_keys_allowed=self._resolver.allows_server_keys,
            kite_redirect_url=self._app.kite_redirect_url,
        )

    def update(self, patch: SettingsUpdate) -> SettingsView:
        changes = patch.model_dump(exclude_none=True)
        if "advisor_id" in changes:
            self._resolver.ensure_available(changes["advisor_id"])
        if "default_style" in changes:
            get_style(changes["default_style"])
        if changes.pop("unlink_telegram", False):
            changes["telegram_chat_id"] = None
        self._repo.update(self._user_id, **changes)
        return self.view()

    def set_credential(self, kind: str, data: CredentialInput) -> SettingsView:
        if kind not in CREDENTIAL_KINDS:
            raise ValidationError(f"Unknown credential '{kind}'")
        key = data.api_key.strip()
        if len(key) < 6:
            raise ValidationError("API key looks too short")
        if kind == "kite":
            secret = (data.api_secret or "").strip()
            if len(secret) < 6:
                raise ValidationError("Kite API secret is required")
            self._credentials.set("kite", {"api_key": key, "api_secret": secret}, hint=mask(key))
            self._kite_tokens.clear()  # a token from the old app is useless
        else:
            self._credentials.set(kind, {"api_key": key}, hint=mask(key))
        return self.view()

    def delete_credential(self, kind: str) -> SettingsView:
        if kind not in CREDENTIAL_KINDS:
            raise ValidationError(f"Unknown credential '{kind}'")
        self._credentials.delete(kind)
        if kind == "kite":
            self._kite_tokens.clear()
        return self.view()

    @staticmethod
    def styles() -> list[dict[str, str | int]]:
        return [{"key": s.key, "label": s.label, "description": s.description,
                 "min_auto_interval_min": s.min_auto_interval_min} for s in STYLES.values()]


class WalletState(BaseModel):
    deployable: float
    broker_cash: float | None


class WalletService:
    """The amount the user is willing to deploy now (user-controlled, not the broker balance)."""

    def __init__(self, repo: WalletRepository, broker: BrokerPort) -> None:
        self._repo = repo
        self._broker = broker

    def deployable(self) -> float:
        return self._repo.get()

    def set_deployable(self, amount: float) -> WalletState:
        if amount < 0:
            raise ValidationError("Amount cannot be negative")
        self._repo.set(round(float(amount), 2))
        return self.state()

    def spend(self, amount: float) -> None:
        self._repo.set(round(max(self._repo.get() - amount, 0.0), 2))

    def state(self) -> WalletState:
        return WalletState(deployable=self.deployable(), broker_cash=self._broker_cash())

    def _broker_cash(self) -> float | None:
        try:
            return self._broker.available_cash() if self._broker.is_authenticated() else None
        except EZTradingError as exc:  # reference figure only, never fatal
            log.warning("Could not read broker cash: %s", exc)
            return None


class PortfolioService:
    def __init__(self, broker: BrokerPort) -> None:
        self._broker = broker

    def summary(self) -> PortfolioSummary:
        return PortfolioSummary.from_holdings(self._broker.holdings())
