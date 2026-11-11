import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import build_app_container
from app.domain.errors import ConflictError
from app.main import create_app
from app.repositories.users import CredentialRepository
from app.security.crypto import SecretBox


@pytest.mark.parametrize("path", ["/api/me", "/api/portfolio", "/api/settings", "/api/plan", "/api/orders", "/api/ipos"])
def test_api_requires_sign_in(env, path):
    r = env.anonymous().get(path)
    assert r.status_code == 401 and r.json()["auth_required"]


def test_public_endpoints(env):
    c = env.anonymous()
    assert c.get("/healthz").json() == {"ok": True}
    cfg = c.get("/api/config").json()
    assert cfg["google_enabled"] is False and cfg["telegram_enabled"] is True and cfg["password_login"] is True
    assert cfg["fixed_otp"] == "7891"


def test_csrf_header_required_for_mutations(env):
    c = env.client()
    assert c.put("/api/wallet", json={"deployable": 1}, headers={"X-Requested-With": ""}).status_code == 403
    assert c.put("/api/wallet", json={"deployable": 1}).status_code == 200


def test_fixed_code_never_used_in_production(settings):
    assert settings.otp_override == "7891"
    prod = settings.model_copy(update={"env": "production"})
    assert prod.otp_override == ""
    assert Settings(_env_file=None).premium_required is True  # Premium is enforced unless turned off


def test_users_are_isolated(env):
    a, b = env.client("a@example.com"), env.client("b@example.com")
    a.put("/api/wallet", json={"deployable": 1000})
    assert a.get("/api/wallet").json()["deployable"] == 1000
    assert b.get("/api/wallet").json()["deployable"] == 0
    a.put("/api/wallet", json={"deployable": 5000})
    plan = a.post("/api/analyze", json={"style": "swing"}).json()
    assert b.get("/api/plan").json() is None
    assert b.delete(f"/api/plans/{plan['id']}").status_code == 404
    assert b.post(f"/api/plans/{plan['id']}/suggestions/X-BUY/ignore").status_code == 404


def test_credentials_are_encrypted_and_masked(env):
    c = env.client()
    r = c.put("/api/credentials/kite", json={"api_key": "kiteapikey1234", "api_secret": "supersecretvalue"})
    body = r.json()
    assert body["credentials"]["kite"] == "••••1234"
    assert "supersecret" not in r.text and "kiteapikey1234" not in r.text
    assert body["kite_redirect_url"].endswith("/auth/kite/callback")
    with env.container.session_factory() as db:
        from app.db.models import Credential
        stored = db.query(Credential).one()
        assert "supersecret" not in stored.secret_enc
        repo = CredentialRepository(db, env.container.box, stored.user_id)
        assert repo.get("kite")["api_secret"] == "supersecretvalue"
    assert c.put("/api/credentials/kite", json={"api_key": "kiteapikey1234"}).status_code == 400
    assert c.delete("/api/credentials/kite").json()["credentials"]["kite"] is None


def test_advisor_options_and_switching(env):
    c = env.client()
    options = {o["id"]: o for o in c.get("/api/advisors").json()}
    assert options["gemini:gemini-3.6-flash"]["key_source"] == "server"
    assert options["claude:claude-opus-5-5"]["available"] is False
    assert options["rules"]["available"] is True
    assert c.put("/api/settings", json={"advisor_id": "claude:claude-opus-5-5"}).status_code == 400
    c.put("/api/credentials/claude", json={"api_key": "sk-ant-user-key"})
    options = {o["id"]: o for o in c.get("/api/advisors").json()}
    assert options["claude:claude-opus-5-5"]["key_source"] == "user"
    assert c.put("/api/settings", json={"advisor_id": "claude:claude-opus-5-5"}).json()["advisor_id"] == "claude:claude-opus-5-5"
    assert c.get("/api/status").json()["advisor_label"] == "Claude Opus 5.5"


def test_schedule_interval_respects_style_minimum(env):
    c = env.client()
    assert c.post("/api/schedules", json={"style": "swing", "interval_min": 5}).status_code == 400
    ok = c.post("/api/schedules", json={"style": "intraday", "interval_min": 5})
    assert ok.status_code == 201 and ok.json()["enabled"] is True
    sid = ok.json()["id"]
    assert c.put(f"/api/schedules/{sid}", json={"style": "positional"}).status_code == 400  # 5 min < 60
    assert c.put(f"/api/schedules/{sid}", json={"style": "positional", "interval_min": 120}).json()["style"] == "positional"


def test_schedules_crud_and_isolation(env):
    a, b = env.client("a@example.com"), env.client("b@example.com")
    s1 = a.post("/api/schedules", json={"style": "intraday", "interval_min": 15}).json()
    a.post("/api/schedules", json={"style": "swing", "interval_min": 60, "enabled": False})
    assert [(s["style"], s["enabled"]) for s in a.get("/api/schedules").json()] == [("intraday", True), ("swing", False)]

    assert b.get("/api/schedules").json() == []
    assert b.put(f"/api/schedules/{s1['id']}", json={"enabled": False}).status_code == 404
    assert b.delete(f"/api/schedules/{s1['id']}").status_code == 404

    assert a.put(f"/api/schedules/{s1['id']}", json={"enabled": False}).json()["enabled"] is False
    assert a.delete(f"/api/schedules/{s1['id']}").status_code == 204
    assert [s["style"] for s in a.get("/api/schedules").json()] == ["swing"]


def test_google_sign_in_adopts_matching_dev_account_only(env):
    with env.container.session_factory() as db:  # an account left over from the old passwordless dev login
        users = env.container.users(db)
        dev_id = users.upsert("dev:me@example.com", "me@example.com", "Me", "", "rules").id
        assert users.upsert("google-123", "Me@Example.com", "Me", "", "rules").id == dev_id   # keeps the dev account's data
        assert users.upsert("google-123", "me@example.com", "Me", "", "rules").id == dev_id   # idempotent
        with pytest.raises(ConflictError):
            users.upsert("google-999", "me@example.com", "Impostor", "", "rules")           # real account isn't taken over


def test_schedule_limit(env):
    c = env.client()
    for i in range(10):
        assert c.post("/api/schedules", json={"style": "swing", "interval_min": 60 + i}).status_code == 201
    assert c.post("/api/schedules", json={"style": "swing", "interval_min": 200}).status_code == 400


def test_duplicate_schedules_rejected(env):
    c = env.client()
    first = c.post("/api/schedules", json={"style": "swing", "interval_min": 30}).json()
    dup = c.post("/api/schedules", json={"style": "swing", "interval_min": 30, "enabled": False})
    assert dup.status_code == 400 and "already have a Swing schedule every 30 min" in dup.json()["detail"]
    other = c.post("/api/schedules", json={"style": "swing", "interval_min": 45}).json()
    assert c.put(f"/api/schedules/{other['id']}", json={"interval_min": 30}).status_code == 400
    assert c.put(f"/api/schedules/{first['id']}", json={"interval_min": 30, "enabled": False}).status_code == 200


def test_secretbox_roundtrip_and_production_requires_key():
    box = SecretBox.from_settings(Settings(_env_file=None))
    assert box.decrypt_json(box.encrypt_json({"a": "b"})) == {"a": "b"}
    with pytest.raises(RuntimeError):
        SecretBox.from_settings(Settings(_env_file=None, env="production"))
