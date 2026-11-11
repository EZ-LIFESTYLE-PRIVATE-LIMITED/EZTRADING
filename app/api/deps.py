"""FastAPI dependencies: DB session, signed-in user, per-user services, CSRF guard."""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.container import AppContainer, UserServices
from app.domain.errors import AuthRequiredError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "fetch"


def get_app(request: Request) -> AppContainer:
    return request.app.state.container


def get_db(app: AppContainer = Depends(get_app)) -> Iterator[Session]:
    db = app.session_factory()
    try:
        yield db
    finally:
        db.close()


def current_user_id(request: Request, db: Session = Depends(get_db), app: AppContainer = Depends(get_app)) -> int:
    uid = request.session.get("uid")
    if not uid or app.users(db).get(int(uid)) is None:
        request.session.clear()
        raise AuthRequiredError("Please sign in")
    return int(uid)


def get_services(
    user_id: int = Depends(current_user_id), db: Session = Depends(get_db), app: AppContainer = Depends(get_app)
) -> UserServices:
    return app.for_user(db, user_id)


def csrf_guard(request: Request) -> None:
    """Cross-site forms can't set custom headers; our fetch() calls always do."""
    if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status_code=403, detail="Missing CSRF header")
