"""One user's Kite Connect session.

Owns the KiteConnect client and that user's daily access token, so the broker
adapter and the Kite price-history adapter share one authenticated client (DRY).
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from kiteconnect import KiteConnect
from kiteconnect import exceptions as kite_exc

from app.domain.errors import BrokerAuthError, BrokerError
from app.domain.ports import TokenStore

log = logging.getLogger(__name__)
T = TypeVar("T")


class KiteSession:
    def __init__(self, api_key: str, api_secret: str, tokens: TokenStore) -> None:
        self._api_secret = api_secret
        self._tokens = tokens
        self._kite = KiteConnect(api_key=api_key)
        token = tokens.load()
        if token:
            self._kite.set_access_token(token)
        self._authenticated = token is not None

    def login_url(self) -> str:
        return self._kite.login_url()

    def complete_login(self, request_token: str) -> None:
        try:
            session = self._kite.generate_session(request_token, api_secret=self._api_secret)
        except kite_exc.KiteException as exc:
            raise BrokerAuthError(f"Kite login failed: {exc}") from exc
        token = session["access_token"]
        self._kite.set_access_token(token)
        self._tokens.save(token)
        self._authenticated = True

    def is_authenticated(self) -> bool:
        return self._authenticated

    def call(self, fn: Callable[[KiteConnect], T]) -> T:
        """Run a Kite API call, translating vendor errors into domain errors."""
        if not self._authenticated:
            raise BrokerAuthError("Kite is not connected today. Click 'Connect Kite'.")
        try:
            return fn(self._kite)
        except kite_exc.TokenException as exc:
            self._tokens.clear()
            self._authenticated = False
            raise BrokerAuthError("Kite session expired, please connect again") from exc
        except kite_exc.KiteException as exc:
            raise BrokerError(f"Kite: {exc}") from exc

    def ltp(self, keys: list[str]) -> dict[str, Any]:
        return self.call(lambda k: k.ltp(keys))
