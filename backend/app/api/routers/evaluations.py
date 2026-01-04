from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import InternalAuthDep, get_db
from app.application.detection.evaluation_service import EvaluationService
from app.domain.enums import RunType
from app.infra.repositories.institution_repo import InstitutionNotFoundError, InstitutionRepository
from app.infra.repositories.profile_repo import ProfileNotFoundError
from app.infra.repositories.dsl_repo import DslNotFoundError

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


class EvaluateInstitutionRequest(BaseModel):
    as_of_date: date
    run_type: RunType


class EvaluateRunRequest(BaseModel):
    as_of_date: date
    run_type: RunType


@router.post(
    "/institutions/{institution_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[InternalAuthDep],
)
def evaluate_institution_day(
    institution_id: uuid.UUID, req: EvaluateInstitutionRequest, db: Session = Depends(get_db)
) -> dict:
    svc = EvaluationService(db)
    try:
        result = svc.evaluate_institution_day(
            institution_id=institution_id, as_of_date=req.as_of_date, run_type=req.run_type
        )
        ev_id = result.get("evaluation_id")
        if ev_id:
            from app.workers.celery_app import celery_app

            celery_app.send_task("llm.explain_evaluation", args=(ev_id,))
            celery_app.send_task("notifications.process_evaluation", args=(ev_id,))
        return result
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="effective_profile_not_found")
    except DslNotFoundError:
        raise HTTPException(status_code=404, detail="effective_dsl_not_found")


@router.post("/run", status_code=status.HTTP_200_OK, dependencies=[InternalAuthDep])
def evaluate_run(req: EvaluateRunRequest, db: Session = Depends(get_db)) -> dict:
    inst_repo = InstitutionRepository(db)
    insts = inst_repo.list_active()
    svc = EvaluationService(db)
    results = []
    for inst in insts:
        r = svc.evaluate_institution_day(institution_id=inst.id, as_of_date=req.as_of_date, run_type=req.run_type)
        ev_id = r.get("evaluation_id")
        if ev_id:
            from app.workers.celery_app import celery_app

            celery_app.send_task("llm.explain_evaluation", args=(ev_id,))
            celery_app.send_task("notifications.process_evaluation", args=(ev_id,))
        results.append(r)
    return {"count": len(results), "results": results}


