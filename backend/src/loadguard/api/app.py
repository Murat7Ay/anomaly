from __future__ import annotations

import uuid

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from loadguard.api.routers import incidents, institutions, ops
from loadguard.core.config import get_settings
from loadguard.core.errors import AppError
from loadguard.core.logging import configure_logging, get_logger

log = get_logger(__name__)


class RequestContext(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=rid, path=request.url.path, method=request.method)
        try:
            resp = await call_next(request)
            resp.headers["X-Request-Id"] = rid
            return resp
        finally:
            structlog.contextvars.clear_contextvars()


def _problem(status: int, code: str, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse(
        {
            "type": f"https://loadguard/errors/{code}",
            "title": code,
            "status": status,
            "detail": detail,
            **extra,
        },
        status_code=status,
        media_type="application/problem+json",
    )


def create_app() -> FastAPI:
    st = get_settings()
    configure_logging(st.log_level, json=st.log_json)
    app = FastAPI(
        title="LoadGuard API",
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
        version="2.0.0",
        description="Borç yükleme teslimat gözetimi: açıklanabilir tespit, olay yönetimi, danışman yapay zekâ.",
    )
    app.add_middleware(RequestContext)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=st.cors_list(),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
    )

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return _problem(exc.status, exc.code, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]
        return _problem(422, "validation", "İstek doğrulanamadı", errors=errs)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", error=str(exc))
        return _problem(500, "internal", "Beklenmeyen bir hata oluştu")

    for r in (ops.router, incidents.router, institutions.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
