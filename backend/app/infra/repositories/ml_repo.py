from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infra.db.models.ml import InstitutionMlArtifact


class MlArtifactRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        profile_config_version_id: uuid.UUID,
        algorithm_version: str,
    ) -> InstitutionMlArtifact | None:
        stmt = select(InstitutionMlArtifact).where(
            and_(
                InstitutionMlArtifact.institution_id == institution_id,
                InstitutionMlArtifact.as_of_date == as_of_date,
                InstitutionMlArtifact.profile_config_version_id == profile_config_version_id,
                InstitutionMlArtifact.algorithm_version == algorithm_version,
            )
        )
        return self._db.execute(stmt).scalars().first()

    def upsert(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        profile_config_version_id: uuid.UUID,
        algorithm_version: str,
        artifact_hash: str,
        artifact_json: dict,
    ) -> InstitutionMlArtifact:
        existing = self.get(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_config_version_id,
            algorithm_version=algorithm_version,
        )
        if existing:
            return existing
        row = InstitutionMlArtifact(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_config_version_id,
            algorithm_version=algorithm_version,
            artifact_hash=artifact_hash,
            artifact_json=artifact_json,
        )
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing2 = self.get(
                institution_id=institution_id,
                as_of_date=as_of_date,
                profile_config_version_id=profile_config_version_id,
                algorithm_version=algorithm_version,
            )
            if existing2:
                return existing2
            raise
        self._db.refresh(row)
        return row


