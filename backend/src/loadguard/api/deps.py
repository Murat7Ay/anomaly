from __future__ import annotations

import hmac
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header
from sqlalchemy.orm import Session

from loadguard.core.config import get_settings
from loadguard.core.errors import Forbidden, Unauthorized
from loadguard.db.models import User
from loadguard.db.session import session_factory


def get_session() -> Iterator[Session]:
    """Request-scoped unit of work: commit when the handler returns, roll back on any exception."""
    s = session_factory()()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


DB = Annotated[Session, Depends(get_session)]


@dataclass(frozen=True)
class Principal:
    username: str
    display_name: str
    role: str  # ANALYST | APPROVER | ADMIN


def issue_token(user: User) -> str:
    st = get_settings()
    now = datetime.now(UTC)  # wall clock on purpose: security must not follow a simulated clock
    claims = {
        "sub": user.username,
        "name": user.display_name,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=st.jwt_ttl_minutes),
        "iss": "loadguard-dev",
    }
    return jwt.encode(claims, st.jwt_secret.get_secret_value(), algorithm="HS256")


@lru_cache(maxsize=1)
def _jwks() -> jwt.PyJWKClient:
    url = get_settings().oidc_jwks_url
    if not url:
        raise Unauthorized("OIDC yapılandırılmamış")
    return jwt.PyJWKClient(url)


def _decode(token: str) -> dict[str, Any]:
    st = get_settings()
    try:
        if st.auth_mode == "dev":
            return jwt.decode(
                token, st.jwt_secret.get_secret_value(), algorithms=["HS256"], issuer="loadguard-dev"
            )
        key = _jwks().get_signing_key_from_jwt(token)
        return jwt.decode(
            token, key.key, algorithms=["RS256", "ES256"], audience=st.oidc_audience, issuer=st.oidc_issuer
        )
    except jwt.PyJWTError as e:
        raise Unauthorized("Geçersiz veya süresi dolmuş oturum") from e


def current_user(s: DB, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Oturum gerekli")
    claims = _decode(authorization.split(" ", 1)[1])
    username = str(claims.get("preferred_username") or claims["sub"])
    user = s.get(User, username)
    if user is None or not user.active:
        # Identity comes from the IdP, authorisation (role) from our own table: least privilege by default.
        raise Forbidden("Kullanıcı bu uygulamada yetkilendirilmemiş")
    return Principal(user.username, user.display_name, user.role)


CurrentUser = Annotated[Principal, Depends(current_user)]


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    def dep(user: CurrentUser) -> Principal:
        if user.role not in roles:
            raise Forbidden("Bu işlem için yetkiniz yok")
        return user

    return Depends(dep)


def ingest_auth(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().ingest_api_key.get_secret_value()
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise Unauthorized("Geçersiz entegrasyon anahtarı")
