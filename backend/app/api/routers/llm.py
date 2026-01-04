from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import InternalAuthDep, get_db
from app.application.llm.explainer_service import LlmExplainerService
from app.infra.repositories.llm_repo import LlmExplanationRepository

router = APIRouter(prefix="/llm", tags=["llm"])


class LlmExplanationResponse(BaseModel):
    id: uuid.UUID
    evaluation_id: uuid.UUID
    status: str
    model_name: str
    requested_at_utc: str
    completed_at_utc: str | None
    prompt_json: dict
    prompt_text: str
    response_json: dict | None
    response_text: str | None
    error_text: str | None


@router.get("/evaluations/{evaluation_id}", response_model=LlmExplanationResponse, dependencies=[InternalAuthDep])
def get_llm_explanation(evaluation_id: uuid.UUID, db: Session = Depends(get_db)) -> LlmExplanationResponse:
    repo = LlmExplanationRepository(db)
    row = repo.get_for_evaluation(evaluation_id)
    if not row:
        raise HTTPException(status_code=404, detail="llm_explanation_not_found")
    return LlmExplanationResponse(
        id=row.id,
        evaluation_id=row.evaluation_id,
        status=row.status.value if hasattr(row.status, "value") else str(row.status),
        model_name=row.model_name,
        requested_at_utc=row.requested_at_utc.isoformat(),
        completed_at_utc=row.completed_at_utc.isoformat() if row.completed_at_utc else None,
        prompt_json=row.prompt_json,
        prompt_text=row.prompt_text,
        response_json=row.response_json,
        response_text=row.response_text,
        error_text=row.error_text,
    )


@router.post("/evaluations/{evaluation_id}/run", dependencies=[InternalAuthDep])
def run_llm_explanation(evaluation_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    svc = LlmExplainerService(db)
    return svc.explain_evaluation(evaluation_id=evaluation_id)


