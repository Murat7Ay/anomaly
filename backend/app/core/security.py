from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_internal_api_key(x_internal_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not x_internal_api_key or x_internal_api_key != settings.internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def require_actor_id(x_actor_id: str | None = Header(default=None)) -> str:
    """
    Simple actor identifier for auditability in internal environments.

    In production, this should be derived from the organisation's IAM / SSO identity and tied to an audit trail.
    """
    if not x_actor_id or not x_actor_id.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="missing_actor_id")
    return x_actor_id.strip()


