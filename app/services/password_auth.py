"""Email + password sign-in, with a 6-digit email code to verify new accounts and reset passwords.

Responses never reveal whether an email is registered: sign-up, resend and forgot-password always
answer the same way, and the email itself tells the owner what to do.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from app.config import Settings
from app.domain.errors import RateLimitedError, ValidationError
from app.domain.models import EmailMessage
from app.domain.ports import EmailSenderPort
from app.repositories.auth import LoginAttemptRepository, OtpRepository
from app.repositories.users import UserRepository
from app.security.passwords import MIN_PASSWORD_LENGTH, hash_otp, hash_password, new_otp, verify_password

log = logging.getLogger(__name__)

SIGNUP, RESET = "signup", "reset"
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
FAIL_WINDOW = timedelta(minutes=15)
MAX_FAILS_PER_EMAIL = 8
MAX_FAILS_PER_IP = 30
WRONG_LOGIN = "Wrong email or password"


@dataclass
class LoginResult:
    user_id: int | None  # set when signed in
    needs_verification: bool = False  # True: a code was emailed; call verify()


class PasswordAuthService:
    def __init__(self, settings: Settings, users: UserRepository, otps: OtpRepository,
                 attempts: LoginAttemptRepository, email: EmailSenderPort, clock: Callable[[], datetime]) -> None:
        self._settings = settings
        self._users = users
        self._otps = otps
        self._attempts = attempts
        self._email = email
        self._clock = clock

    # --- sign-up -------------------------------------------------------------
    def signup(self, email: str, name: str, password: str) -> None:
        email = _norm(email)
        _check_password(password)
        user = self._users.by_email(email)
        if user is None:
            self._users.create_password_user(email, name.strip() or email.split("@")[0], hash_password(password),
                                             self._settings.new_user_advisor)
            self._send_code(email, SIGNUP)
        elif not user.email_verified:  # an earlier sign-up that was never confirmed: start over
            self._users.update(user, password_hash=hash_password(password), name=name.strip() or user.name)
            self._send_code(email, SIGNUP)
        else:  # the address already has an account; tell its owner instead of the requester
            self._notify(email, "You already have an EZTrading account",
                         "Someone (hopefully you) tried to create an EZTrading account with this email, but one "
                         "already exists. Sign in instead, or use 'Forgot password' to set a new password.")

    def verify(self, email: str, code: str) -> int:
        email = _norm(email)
        self._check_code(email, SIGNUP, code)
        user = self._users.by_email(email)
        if user is None:
            raise ValidationError("That code is wrong or has expired")
        self._users.update(user, email_verified=True)
        return user.id

    def resend(self, email: str) -> None:
        email = _norm(email)
        user = self._users.by_email(email)
        if user is not None and not user.email_verified and user.password_hash:
            self._send_code(email, SIGNUP)

    # --- sign-in -------------------------------------------------------------
    def login(self, email: str, password: str, ip: str) -> LoginResult:
        email = _norm(email)
        now = self._clock()
        email_key, ip_key = f"email:{email}", f"ip:{ip}"
        if (self._attempts.count_since(email_key, now - FAIL_WINDOW) >= MAX_FAILS_PER_EMAIL
                or self._attempts.count_since(ip_key, now - FAIL_WINDOW) >= MAX_FAILS_PER_IP):
            raise RateLimitedError("Too many sign-in attempts. Wait 15 minutes or reset your password.")
        user = self._users.by_email(email)
        if not verify_password(user.password_hash if user else None, password):
            self._attempts.add([email_key, ip_key], now, prune_before=now - timedelta(days=1))
            raise ValidationError(WRONG_LOGIN)
        self._attempts.clear(email_key)
        if not user.email_verified:
            self._send_code(email, SIGNUP, enforce_cooldown=False)
            return LoginResult(user_id=None, needs_verification=True)
        return LoginResult(user_id=user.id)

    # --- password reset -----------------------------------------------------
    def forgot(self, email: str) -> None:
        email = _norm(email)
        if self._users.by_email(email) is not None:
            self._send_code(email, RESET)

    def reset(self, email: str, code: str, new_password: str) -> int:
        email = _norm(email)
        _check_password(new_password)
        self._check_code(email, RESET, code)
        user = self._users.by_email(email)
        if user is None:
            raise ValidationError("That code is wrong or has expired")
        # Receiving the code proves they own the address, so this also verifies it.
        self._users.update(user, password_hash=hash_password(new_password), email_verified=True)
        self._attempts.clear(f"email:{email}")
        return user.id

    # --- codes ---------------------------------------------------------------
    def _send_code(self, email: str, purpose: str, enforce_cooldown: bool = True) -> None:
        now = self._clock()
        existing = self._otps.get(email, purpose)
        if existing is not None and now - existing.last_sent_at < RESEND_COOLDOWN:
            if enforce_cooldown:
                raise RateLimitedError("A code was just sent. Wait a minute before asking for another.")
            return  # a fresh code is already on its way
        code = new_otp()
        self._otps.put(email, purpose, hash_otp(self._settings.session_secret, email, purpose, code), now + OTP_TTL,
                       now)
        what = "confirm your email" if purpose == SIGNUP else "reset your password"
        self._notify(email, f"Your EZTrading code: {code}",
                     f"Your code to {what} is {code}. It expires in {int(OTP_TTL.total_seconds() // 60)} minutes.\n\n"
                     "If you didn't ask for this, you can ignore this email.")

    def _check_code(self, email: str, purpose: str, code: str) -> None:
        row = self._otps.get(email, purpose)
        if row is None or row.expires_at < self._clock():
            raise ValidationError("That code is wrong or has expired")
        expected = hash_otp(self._settings.session_secret, email, purpose, code.strip())
        if not hmac.compare_digest(row.code_hash, expected):
            if self._otps.bump_attempts(row) >= OTP_MAX_ATTEMPTS:
                self._otps.delete(row)
                raise ValidationError("Too many wrong codes. Ask for a new one.")
            raise ValidationError("That code is wrong or has expired")
        self._otps.delete(row)

    def _notify(self, email: str, subject: str, text: str) -> None:
        try:
            self._email.send(EmailMessage(to=email, subject=subject, text=text))
        except Exception:  # noqa: BLE001 - never leak delivery details to the caller
            log.exception("Could not send email to %s", email)
            raise ValidationError("We couldn't send the email right now. Please try again shortly.") from None


def _norm(email: str) -> str:
    return email.strip().lower()


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > 256:
        raise ValidationError("Password is too long")

