import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class Outbox:
    def __init__(self) -> None:
        self.sent = []

    def send(self, message) -> None:
        self.sent.append(message)

    def code(self, to: str) -> str:
        msg = next(m for m in reversed(self.sent) if m.to == to)
        return re.search(r"\b(\d{6})\b", msg.subject).group(1)


@pytest.fixture
def outbox(env):
    box = Outbox()
    env.container.email_sender = box
    env.container.settings.fixed_otp = ""  # these tests check real random codes
    return box


def client(env) -> TestClient:
    return TestClient(create_app(env.container), headers={"X-Requested-With": "fetch"})


def signup(c, email="pw@example.com", password="correct horse"):
    return c.post("/auth/signup", json={"name": "Pat", "email": email, "password": password})


def test_signup_verify_then_login(env, outbox):
    c = client(env)
    assert c.get("/api/config").json()["password_login"] is True
    assert signup(c, "PW@Example.com").json()["next"] == "verify"
    assert c.get("/api/me").status_code == 401  # not signed in until the email is confirmed

    # An unverified account can't sign in yet; logging in re-sends the code.
    r = c.post("/auth/login", json={"email": "pw@example.com", "password": "correct horse"}).json()
    assert r["next"] == "verify"

    assert c.post("/auth/verify", json={"email": "pw@example.com", "code": outbox.code("pw@example.com")}).json()["ok"]
    me = c.get("/api/me").json()
    assert me["email"] == "pw@example.com" and me["name"] == "Pat"

    c2 = client(env)
    assert c2.post("/auth/login", json={"email": "pw@example.com", "password": "wrong pass"}).status_code == 400
    assert c2.post("/auth/login", json={"email": "pw@example.com", "password": "correct horse"}).json()["ok"]
    assert c2.get("/api/me").json()["id"] == me["id"]


def test_wrong_codes_and_expiry(env, outbox):
    c = client(env)
    signup(c)
    good = outbox.code("pw@example.com")
    bad = "000000" if good != "000000" else "111111"
    for _ in range(4):
        assert c.post("/auth/verify", json={"email": "pw@example.com", "code": bad}).status_code == 400
    r = c.post("/auth/verify", json={"email": "pw@example.com", "code": bad})
    assert "Too many wrong codes" in r.json()["detail"]
    assert c.post("/auth/verify", json={"email": "pw@example.com", "code": good}).status_code == 400  # burned

    env.clock.advance(minutes=2)
    c.post("/auth/otp/resend", json={"email": "pw@example.com"})
    fresh = outbox.code("pw@example.com")
    env.clock.advance(minutes=11)
    assert c.post("/auth/verify", json={"email": "pw@example.com", "code": fresh}).status_code == 400  # expired


def test_resend_cooldown(env, outbox):
    c = client(env)
    signup(c)
    assert c.post("/auth/otp/resend", json={"email": "pw@example.com"}).status_code == 429
    env.clock.advance(seconds=61)
    assert c.post("/auth/otp/resend", json={"email": "pw@example.com"}).status_code == 200
    assert len(outbox.sent) == 2


def test_responses_do_not_reveal_registered_emails(env, outbox):
    c = client(env)
    signup(c)
    c.post("/auth/verify", json={"email": "pw@example.com", "code": outbox.code("pw@example.com")})
    c = client(env)
    taken = signup(c, password="another one")
    fresh = signup(c, "new@example.com")
    assert taken.status_code == fresh.status_code == 200 and taken.json() == fresh.json()
    assert "already have an EZTrading account" in outbox.sent[-2].subject  # the owner is told, not the requester
    forgot_known = c.post("/auth/password/forgot", json={"email": "pw@example.com"}).json()
    forgot_unknown = c.post("/auth/password/forgot", json={"email": "nobody@example.com"}).json()
    assert forgot_known == forgot_unknown
    unknown = c.post("/auth/login", json={"email": "nobody@example.com", "password": "whatever1"})
    wrong = c.post("/auth/login", json={"email": "pw@example.com", "password": "whatever1"})
    assert unknown.json() == wrong.json()


def test_forgot_and_reset_password(env, outbox):
    c = client(env)
    signup(c)
    c.post("/auth/verify", json={"email": "pw@example.com", "code": outbox.code("pw@example.com")})
    c = client(env)
    c.post("/auth/password/forgot", json={"email": "pw@example.com"})
    r = c.post("/auth/password/reset", json={"email": "pw@example.com", "code": outbox.code("pw@example.com"),
                                             "password": "short"})
    assert r.status_code == 400 and "at least 8" in r.json()["detail"]
    r = c.post("/auth/password/reset", json={"email": "pw@example.com", "code": outbox.code("pw@example.com"),
                                             "password": "brand new pass"})
    assert r.json()["ok"] and c.get("/api/me").status_code == 200
    c2 = client(env)
    assert c2.post("/auth/login", json={"email": "pw@example.com", "password": "correct horse"}).status_code == 400
    assert c2.post("/auth/login", json={"email": "pw@example.com", "password": "brand new pass"}).json()["ok"]


def test_login_rate_limited(env, outbox):
    c = client(env)
    signup(c)
    for _ in range(8):
        c.post("/auth/login", json={"email": "pw@example.com", "password": "nope nope"})
    assert c.post("/auth/login", json={"email": "pw@example.com", "password": "correct horse"}).status_code == 429
    env.clock.advance(minutes=16)
    assert c.post("/auth/login", json={"email": "pw@example.com", "password": "correct horse"}).status_code == 200


def test_google_links_password_account(env, outbox):
    c = client(env)
    signup(c)
    c.post("/auth/verify", json={"email": "pw@example.com", "code": outbox.code("pw@example.com")})
    uid = c.get("/api/me").json()["id"]
    with env.container.session_factory() as db:
        users = env.container.users(db)
        assert users.upsert("google-1", "pw@example.com", "Pat G", "", "rules").id == uid
        # An unconfirmed sign-up is taken over by the real owner, and the stranger's password is dropped.
        signup(client(env), "victim@example.com", "attacker pass")
        victim = users.upsert("google-2", "victim@example.com", "Victim", "", "rules")
        assert victim.password_hash is None and victim.email_verified is True


def test_password_login_hidden_in_production_without_smtp(env):
    env.container.settings.env = "production"
    c = client(env)
    assert c.get("/api/config").json()["password_login"] is False
    assert signup(c).status_code == 404
    env.container.settings.smtp_host, env.container.settings.smtp_from = "smtp.example.com", "no-reply@example.com"
    assert client(env).get("/api/config").json()["password_login"] is True
