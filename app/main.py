"""FastAPI application factory. Run: uvicorn app.main:app"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.api import auth_routes, billing_routes, routes, webhooks
from app.config import get_settings
from app.container import AppContainer, build_app_container
from app.domain.errors import (
    AdvisorError,
    AuthRequiredError,
    BrokerAuthError,
    BrokerError,
    ConflictError,
    EZTradingError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationError,
)

log = logging.getLogger("eztrading.api")
STATIC_DIR =Path(__file__).resolve().parent.parent / "static"
SESSION_MAX_AGE = 14 * 24 * 3600

_ERROR_STATUS: list[tuple[type[EZTradingError], int]] = [
    (AuthRequiredError, 401),
    (BrokerAuthError, 401),
    (ValidationError, 400),
    (ForbiddenError, 403),
    (NotFoundError, 404),
    (ConflictError, 409),
    (RateLimitedError, 429),
    (AdvisorError, 502),
    (BrokerError, 502),
    (EZTradingError, 502),
]


def create_app(container: AppContainer | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    container = container or build_app_container(get_settings())
    settings = container.settings

    app = FastAPI(title="EZTrading", version="2.0.0")
    app.state.container = container
    app.state.oauth = auth_routes.build_oauth(settings)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="ezt_session",
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=settings.is_production,
    )

    @app.exception_handler(EZTradingError)
    async def _domain_error(request: Request, exc: EZTradingError) -> JSONResponse:
        code = next(status for cls, status in _ERROR_STATUS if isinstance(exc, cls))
        if code >= 500:
            log.warning("%s %s -> %s %s: %s", request.method, request.url.path, code, type(exc).__name__, exc,
                        exc_info=exc.__cause__ is not None)
        else:
            log.info("%s %s -> %s: %s", request.method, request.url.path, code, exc)
        return JSONResponse(status_code=code, content={
            "detail": str(exc),
            "auth_required": isinstance(exc, AuthRequiredError),
            "kite_login_required": isinstance(exc, BrokerAuthError),
        })

    @app.middleware("http")
    async def _revalidate_static(request: Request, call_next):
        # No build step means no hashed filenames; make browsers revalidate (cheap 304s)
        # so an update never mixes old and new ES modules.
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    app.include_router(routes.public)
    app.include_router(routes.api)
    app.include_router(auth_routes.router)
    app.include_router(webhooks.router)
    app.include_router(billing_routes.api)
    app.include_router(billing_routes.webhooks)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def __getattr__(name: str):
    # Lazily build the module-level app so importing app.main in tests doesn't need .env
    if name == "app":
        globals()["app"] = create_app()
        return globals()["app"]
    raise AttributeError(name)
