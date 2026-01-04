from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import LlmStatus
from app.infra.db.models.llm import LlmExplanation


class LlmExplanationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_for_evaluation(self, evaluation_id: uuid.UUID) -> LlmExplanation | None:
        stmt = select(LlmExplanation).where(LlmExplanation.evaluation_id == evaluation_id)
        return self._db.execute(stmt).scalars().first()

    def create_requested(
        self,
        *,
        evaluation_id: uuid.UUID,
        model_name: str,
        requested_at_utc: datetime,
        prompt_json: dict,
        prompt_text: str,
    ) -> LlmExplanation:
        row = LlmExplanation(
            evaluation_id=evaluation_id,
            status=LlmStatus.PENDING,
            model_name=model_name,
            requested_at_utc=requested_at_utc,
            completed_at_utc=None,
            prompt_json=prompt_json,
            prompt_text=prompt_text,
            response_json=None,
            response_text=None,
            error_text=None,
        )
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            existing = self.get_for_evaluation(evaluation_id)
            if existing:
                return existing
            raise
        self._db.refresh(row)
        return row

    def mark_success(
        self,
        *,
        explanation_id: uuid.UUID,
        completed_at_utc: datetime,
        response_text: str,
        response_json: dict,
    ) -> LlmExplanation:
        row = self._db.get(LlmExplanation, explanation_id)
        if not row:
            raise ValueError("llm_explanation_not_found")
        row.status = LlmStatus.SUCCESS
        row.completed_at_utc = completed_at_utc
        row.response_text = response_text
        row.response_json = response_json
        row.error_text = None
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def mark_failed(
        self,
        *,
        explanation_id: uuid.UUID,
        completed_at_utc: datetime,
        error_text: str,
        response_json: dict | None = None,
    ) -> LlmExplanation:
        row = self._db.get(LlmExplanation, explanation_id)
        if not row:
            raise ValueError("llm_explanation_not_found")
        row.status = LlmStatus.FAILED
        row.completed_at_utc = completed_at_utc
        row.error_text = error_text
        row.response_json = response_json
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row


