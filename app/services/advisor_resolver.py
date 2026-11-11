"""Resolves which advisor a user can use and with whose API key.

The user's own key always wins. The server's key is a fallback only for users allowed to use it
(premium users, or everyone where premium isn't enforced).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.adapters.llm.factory import create_llm_client, registered_providers
from app.config import ADVISOR_CATALOG, Settings, advisor_option
from app.domain.errors import AdvisorError, PremiumRequiredError, ValidationError
from app.domain.ports import LLMClientPort, PortfolioAdvisorPort
from app.repositories.users import CredentialRepository
from app.services.advice.llm_advisors import LLMIpoAdvisor, LLMPortfolioAdvisor
from app.services.advice.rules import RulesAdvisor
from app.services.styles import TradingStyle

RULES_ID = "rules"


class AdvisorOptionView(BaseModel):
    id: str
    label: str
    provider: str
    available: bool
    key_source: str  # "user" | "server" | "premium" (server key, but locked) | "none" | "builtin"


class AdvisorResolver:
    def __init__(self, settings: Settings, credentials: CredentialRepository, allow_server_keys: bool = True) -> None:
        self._settings = settings
        self._credentials = credentials
        self._allow_server_keys = allow_server_keys

    @property
    def allows_server_keys(self) -> bool:
        return self._allow_server_keys

    def _source(self, provider: str, user_kinds: set[str]) -> str:
        if provider in user_kinds:
            return "user"
        if provider in self._settings.server_api_keys:
            return "server" if self._allow_server_keys else "premium"
        return "none"

    def options(self) -> list[AdvisorOptionView]:
        user_kinds = set(self._credentials.hints())
        providers = registered_providers()
        views = []
        for opt in ADVISOR_CATALOG:
            if opt.provider == RULES_ID:
                views.append(AdvisorOptionView(id=opt.id, label=opt.label, provider=opt.provider,
                                               available=True, key_source="builtin"))
                continue
            if opt.provider not in providers:
                continue
            source = self._source(opt.provider, user_kinds)
            views.append(AdvisorOptionView(id=opt.id, label=opt.label, provider=opt.provider,
                                           available=source in ("user", "server"), key_source=source))
        return views

    def ensure_available(self, advisor_id: str) -> None:
        view = next((o for o in self.options() if o.id == advisor_id), None)
        if view is None:
            raise ValidationError(f"Unknown advisor '{advisor_id}'")
        if view.key_source == "premium":
            raise PremiumRequiredError(f"{view.label} with the server's key is a Premium feature. "
                                       "Add your own API key in Settings, or upgrade to Premium.")
        if not view.available:
            raise ValidationError(f"No API key for {view.label}. Add one in Settings.")

    def label(self, advisor_id: str) -> str:
        opt = advisor_option(advisor_id)
        return opt.label if opt else advisor_id

    def portfolio_advisor(self, advisor_id: str, style: TradingStyle) -> PortfolioAdvisorPort:
        client = self._client(advisor_id)
        return RulesAdvisor(style) if client is None else LLMPortfolioAdvisor(client, style)

    def ipo_advisor(self, advisor_id: str) -> LLMIpoAdvisor | None:
        client = self._client(advisor_id)
        return None if client is None else LLMIpoAdvisor(client)

    def _client(self, advisor_id: str) -> LLMClientPort | None:
        opt = advisor_option(advisor_id)
        if opt is None:
            raise AdvisorError(f"Unknown advisor '{advisor_id}'. Pick one in the advisor menu.")
        if opt.provider == RULES_ID:
            return None
        key = (self._credentials.get(opt.provider) or {}).get("api_key")
        if not key and opt.provider in self._settings.server_api_keys:
            if not self._allow_server_keys:
                raise PremiumRequiredError(f"{opt.label} with the server's key is a Premium feature. "
                                           "Add your own API key in Settings, pick Rules, or upgrade to Premium.")
            key = self._settings.server_api_keys[opt.provider]
        if not key:
            raise AdvisorError(f"No API key for {opt.label}. Add your key in Settings or choose another advisor.")
        return create_llm_client(opt.provider, opt.model, key, self._settings)
