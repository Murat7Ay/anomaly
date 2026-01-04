from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.security import require_actor_id, require_internal_api_key
from app.infra.db.session import db_session


def get_db() -> Generator[Session, None, None]:
    yield from db_session()


InternalAuthDep = Depends(require_internal_api_key)
ActorIdDep = Depends(require_actor_id)


