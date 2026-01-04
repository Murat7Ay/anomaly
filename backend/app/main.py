from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.calendars import router as calendars_router
from app.api.routers.dsl import router as dsl_router
from app.api.routers.evaluations import router as evaluations_router
from app.api.routers.health import router as health_router
from app.api.routers.institutions import router as institutions_router
from app.api.routers.llm import router as llm_router
from app.api.routers.replay import router as replay_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger(__name__)
    log.info("app_starting", env=settings.app_env, name=settings.app_name)

    app = FastAPI(title=settings.app_name)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins(),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id"],
        max_age=600,
    )
    app.include_router(health_router)
    app.include_router(calendars_router)
    app.include_router(institutions_router)
    app.include_router(dsl_router)
    app.include_router(evaluations_router)
    app.include_router(llm_router)
    app.include_router(replay_router)
    return app


app = create_app()


