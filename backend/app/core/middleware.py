from __future__ import annotations

import uuid

import structlog
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Binds request-scoped context (request_id, actor_id) into structlog contextvars.

    - Reads X-Request-Id if provided; otherwise generates one.
    - Reads X-Actor-Id if provided (best-effort; required for write endpoints separately).
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        actor_id = request.headers.get("x-actor-id")

        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            actor_id=actor_id,
            path=request.url.path,
            method=request.method,
        )
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            structlog.contextvars.clear_contextvars()


