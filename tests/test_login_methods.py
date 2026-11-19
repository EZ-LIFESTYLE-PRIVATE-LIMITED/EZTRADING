"""LOGIN_METHODS picks which sign-in options the login page offers (e.g. Google live, dev in a sandbox).

"dev" is email sign-in where the code is always FIXED_OTP, so a sandbox needs no inbox.
"""

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


def test_unset_keeps_existing_behaviour():
    s = make(**GOOGLE)
    assert s.google_enabled and s.password_login_enabled and s.otp_override == "7891"
    p = prod(**GOOGLE)
    assert p.google_enabled and not p.password_login_enabled and p.otp_override == ""


def test_google_only():
    s = make(login_methods="google", **GOOGLE)
    assert s.google_enabled and not s.password_login_enabled
    assert s.login_config_warnings() == []


def test_google_listed_without_keys_is_off_and_warns():
    s = make(login_methods="google")
    assert not s.google_enabled
    assert any("GOOGLE_CLIENT_ID" in w for w in s.login_config_warnings())


def test_dev_only_sandbox_in_development():
    s = make(login_methods="dev", **GOOGLE)
    assert s.password_login_enabled and s.otp_override == "7891" and not s.google_enabled


def test_dev_in_production_needs_allowlist():
    off = prod(login_methods="dev")
    assert not off.password_login_enabled and off.otp_override == ""
    assert any("ALLOWED_EMAILS" in w for w in off.login_config_warnings())
    sandbox = prod(login_methods="dev", allowed_emails="me@example.com")
    assert sandbox.password_login_enabled and sandbox.otp_override == "7891"
    assert any("ON in production" in w for w in sandbox.login_config_warnings())


def test_password_in_production_uses_real_codes():
    s = prod(login_methods="password", smtp_host="smtp.example.com", smtp_from="a@example.com",
             allowed_emails="me@example.com")
    assert s.password_login_enabled and s.otp_override == ""


def test_unknown_method_warns():
    assert any("unknown" in w for w in make(login_methods="google,sms", **GOOGLE).login_config_warnings())


@pytest.mark.parametrize("methods, expect", [
    ("google", {"google_enabled": True, "password_login": False}),
    ("dev", {"google_enabled": False, "password_login": True}),
    ("google,password", {"google_enabled": True, "password_login": True}),
])
def test_config_endpoint_reflects_methods(env, methods, expect):
    s = env.container.settings.model_copy(update={"login_methods": methods, **GOOGLE})
    c = TestClient(create_app(build_app_container(s, session_factory=env.container.session_factory)))
    cfg = c.get("/api/config").json()
    assert {k: cfg[k] for k in expect} == expect
    signup = c.post("/auth/signup", json={"email": "x@example.com", "password": "a-long-password-1"},
                    headers={"X-Requested-With": "fetch"})
    assert (signup.status_code == 200) is expect["password_login"]
