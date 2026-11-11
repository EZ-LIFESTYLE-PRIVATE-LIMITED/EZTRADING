"""Inbound webhooks from third parties (authenticated by shared secret, not session)."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_app, get_db
from app.container import AppContainer

router = APIRouter()


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    secret: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
    app: AppContainer = Depends(get_app),
    db: Session = Depends(get_db),
) -> dict:
    expected = app.settings.telegram_webhook_secret
    if not app.settings.telegram_enabled or not expected or not hmac.compare_digest(secret or "", expected):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = await request.json()
    app.telegram_linker(db).handle_update(update)
    return {"ok": True}  # always 200 so Telegram doesn't retry
