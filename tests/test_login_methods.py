"""LOGIN_METHODS picks which sign-in options the login page offers (e.g. Google in production, dev in a sandbox)."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_app_container
from app.main import create_app

GOOGLE = {"google_client_id": "id", "google_client_secret": "secret"}


def make(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def prod(**kw) -> Settings:
    return make(env="production", app_encryption_key=Fernet.generate_key().decode(), **kw)


def test_unset_keeps_legacy_behaviour():
    s = make(dev_login=True, **GOOGLE)
    assert s.google_enabled and s.dev_login_enabled and s.password_login_enabled
    assert not prod(dev_login=True).dev_login_enabled


def test_google_only():
    s = make(login_methods="google", dev_login=True, **GOOGLE)
    assert s.google_enabled and not s.dev_login_enabled and not s.password_login_enabled
    assert s.login_config_warnings() == []


def test_google_listed_without_keys_is_off_and_warns():
    s = make(login_methods="google")
    assert not s.google_enabled
    assert any("GOOGLE_CLIENT_ID" in w for w in s.login_config_warnings())


def test_dev_only_sandbox_in_development():
    s = make(login_methods="dev", **GOOGLE)
    assert s.dev_login_enabled and not s.google_enabled and not s.password_login_enabled


def test_dev_in_production_needs_allowlist():
    assert not prod(login_methods="dev").dev_login_enabled
    assert any("ALLOWED_EMAILS" in w for w in prod(login_methods="dev").login_config_warnings())
    sandbox = prod(login_methods="dev", allowed_emails="me@example.com")
    assert sandbox.dev_login_enabled
    assert any("ON in production" in w for w in sandbox.login_config_warnings())


def test_unknown_method_warns():
    assert any("unknown" in w for w in make(login_methods="google,sms", **GOOGLE).login_config_warnings())


@pytest.mark.parametrize("methods, expect", [
    ("google", {"google_enabled": True, "dev_login": False, "password_login": False}),
    ("dev", {"google_enabled": False, "dev_login": True, "password_login": False}),
    ("google,password,dev", {"google_enabled": True, "dev_login": True, "password_login": True}),
])
def test_config_endpoint_reflects_methods(env, methods, expect):
    s = env.container.settings.model_copy(update={"login_methods": methods, **GOOGLE})
    c = TestClient(create_app(build_app_container(s, session_factory=env.container.session_factory)))
    cfg = c.get("/api/config").json()
    assert {k: cfg[k] for k in expect} == expect
    dev = c.post("/auth/dev-login", json={"email": "x@example.com"}, headers={"X-Requested-With": "fetch"})
    assert (dev.status_code == 200) is expect["dev_login"]
