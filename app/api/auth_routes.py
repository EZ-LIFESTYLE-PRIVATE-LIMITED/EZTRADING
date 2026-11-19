"""Sign-in (Google SSO, email + password), sign-out and the per-user Kite login flow."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import csrf_guard, get_app, get_db, get_services
from app.config import Settings
from app.container import AppContainer, UserServices
from app.domain.errors import BrokerAuthError, ConflictError
from app.services.password_auth import PasswordAuthService

router = APIRouter(prefix="/auth")


def build_oauth(settings: Settings) -> OAuth:
    oauth = OAuth()
    if settings.google_enabled:
        oauth.register(
            name="google",
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            client_kwargs={"scope": "openid email profile"},
        )
    return oauth


def _check_allowed(app: AppContainer, email: str) -> None:
    allowed = app.settings.allowed_email_set
    if allowed and email.strip().lower() not in allowed:
        raise HTTPException(status_code=403, detail="This account is not allowed to use EZTrading")


def _start_session(request: Request, user_id: int) -> None:
    request.session.clear()  # new session on every sign-in (no fixation)
    request.session["uid"] = user_id


def _sign_in(request: Request, app: AppContainer, db: Session, sub: str, email: str, name: str, picture: str) -> None:
    _check_allowed(app, email)
    user = app.users(db).upsert(sub, email, name, picture, app.settings.new_user_advisor)
    _start_session(request, user.id)


@router.get("/google/login")
async def google_login(request: Request, app: AppContainer = Depends(get_app)):
    if not app.settings.google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in is not configured")
    redirect_uri = f"{app.settings.public_base_url.rstrip('/')}/auth/google/callback"
    return await request.app.state.oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, app: AppContainer = Depends(get_app), db: Session = Depends(get_db)):
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/login.html?error=google")
    info = token.get("userinfo") or {}
    if not info.get("email") or not info.get("email_verified"):
        return RedirectResponse("/login.html?error=email")
    try:
        _sign_in(request, app, db, info["sub"], info["email"], info.get("name", ""), info.get("picture", ""))
    except ConflictError:
        return RedirectResponse("/login.html?error=conflict")
    return RedirectResponse("/")


# --- email + password (optional) --------------------------------------------------
class SignupBody(BaseModel):
    name: str = Field(default="", max_length=100)
    email: EmailStr
    password: str


class EmailBody(BaseModel):
    email: EmailStr


class VerifyBody(BaseModel):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ResetBody(VerifyBody):
    password: str


def password_service(app: AppContainer = Depends(get_app), db: Session = Depends(get_db)) -> PasswordAuthService:
    if not app.settings.password_login_enabled:
        raise HTTPException(status_code=404, detail="Email sign-in is not enabled")
    return app.password_auth(db)


CODE_SENT = {"next": "verify", "message": "If this email can be used, we've sent it a code."}


@router.post("/signup", dependencies=[Depends(csrf_guard)])
def signup(body: SignupBody, app: AppContainer = Depends(get_app),
           auth: PasswordAuthService = Depends(password_service)) -> dict:
    _check_allowed(app, body.email)
    auth.signup(body.email, body.name, body.password)
    return CODE_SENT


@router.post("/verify", dependencies=[Depends(csrf_guard)])
def verify(body: VerifyBody, request: Request, auth: PasswordAuthService = Depends(password_service)) -> dict:
    _start_session(request, auth.verify(body.email, body.code))
    return {"ok": True}


@router.post("/otp/resend", dependencies=[Depends(csrf_guard)])
def resend(body: EmailBody, auth: PasswordAuthService = Depends(password_service)) -> dict:
    auth.resend(body.email)
    return CODE_SENT


@router.post("/login", dependencies=[Depends(csrf_guard)])
def login(body: LoginBody, request: Request, app: AppContainer = Depends(get_app),
          auth: PasswordAuthService = Depends(password_service)) -> dict:
    _check_allowed(app, body.email)
    result = auth.login(body.email, body.password, request.client.host if request.client else "unknown")
    if result.needs_verification:
        return {"next": "verify", "message": "Confirm your email first. We've sent you a code."}
    _start_session(request, result.user_id)
    return {"ok": True}


@router.post("/password/forgot", dependencies=[Depends(csrf_guard)])
def forgot(body: EmailBody, auth: PasswordAuthService = Depends(password_service)) -> dict:
    auth.forgot(body.email)
    return {"next": "reset", "message": "If an account uses this email, we've sent it a code."}


@router.post("/password/reset", dependencies=[Depends(csrf_guard)])
def reset(body: ResetBody, request: Request, app: AppContainer = Depends(get_app),
          auth: PasswordAuthService = Depends(password_service)) -> dict:
    _check_allowed(app, body.email)
    _start_session(request, auth.reset(body.email, body.code, body.password))
    return {"ok": True}


@router.post("/logout", dependencies=[Depends(csrf_guard)])
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/kite/login")
def kite_login(services: UserServices = Depends(get_services)) -> RedirectResponse:
    return RedirectResponse(services.broker.login_url())


@router.get("/kite/callback")
def kite_callback(
    request_token: str | None = Query(None),
    status: str | None = Query(None),
    services: UserServices = Depends(get_services),
) -> RedirectResponse:
    if status != "success" or not request_token:
        return RedirectResponse("/?kite=failed")
    try:
        services.broker.complete_login(request_token)
    except BrokerAuthError:
        return RedirectResponse("/?kite=failed")
    return RedirectResponse("/?kite=connected")
