from __future__ import annotations

import uuid
from datetime import date

from app.core.logging import get_logger
from app.domain.enums import RunType
from app.application.llm.explainer_service import LlmExplainerService
from app.application.notifications.notification_service import NotificationService
from app.application.detection.evaluation_service import EvaluationService
from app.infra.db.session import SessionLocal
from app.infra.repositories.institution_repo import InstitutionRepository
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="health.ping")
def ping() -> str:
    log.info("celery_ping")
    return "pong"


@celery_app.task(name="detection.evaluate_institution_day")
def evaluate_institution_day(institution_id: str, as_of_date: str, run_type: str) -> dict:
    inst_id = uuid.UUID(institution_id)
    as_of = date.fromisoformat(as_of_date)
    rt = RunType(run_type)

    db = SessionLocal()
    try:
        svc = EvaluationService(db)
        result = svc.evaluate_institution_day(institution_id=inst_id, as_of_date=as_of, run_type=rt)
        ev_id = result.get("evaluation_id")
        if ev_id:
            celery_app.send_task("llm.explain_evaluation", args=(ev_id,))
            celery_app.send_task("notifications.process_evaluation", args=(ev_id,))
        return result
    finally:
        db.close()


@celery_app.task(name="detection.evaluate_run")
def evaluate_run(run_type: str, as_of_date: str | None = None) -> dict:
    rt = RunType(run_type)
    as_of = date.fromisoformat(as_of_date) if as_of_date else date.today()

    db = SessionLocal()
    try:
        inst_repo = InstitutionRepository(db)
        insts = inst_repo.list_active()
        svc = EvaluationService(db)
        results = []
        for inst in insts:
            r = svc.evaluate_institution_day(institution_id=inst.id, as_of_date=as_of, run_type=rt)
            ev_id = r.get("evaluation_id")
            if ev_id:
                celery_app.send_task("llm.explain_evaluation", args=(ev_id,))
                celery_app.send_task("notifications.process_evaluation", args=(ev_id,))
            results.append(r)
        return {"run_type": run_type, "as_of_date": as_of.isoformat(), "count": len(results), "results": results}
    finally:
        db.close()


@celery_app.task(name="llm.explain_evaluation")
def explain_evaluation(evaluation_id: str) -> dict:
    db = SessionLocal()
    try:
        svc = LlmExplainerService(db)
        return svc.explain_evaluation(evaluation_id=uuid.UUID(evaluation_id))
    finally:
        db.close()


@celery_app.task(name="notifications.process_evaluation")
def process_notification_for_evaluation(evaluation_id: str) -> dict:
    db = SessionLocal()
    try:
        svc = NotificationService(db)
        return svc.process_evaluation(evaluation_id=uuid.UUID(evaluation_id))
    finally:
        db.close()


@celery_app.task(name="notifications.send_warning_digest")
def send_warning_digest(as_of_date: str | None = None) -> dict:
    db = SessionLocal()
    try:
        svc = NotificationService(db)
        d = date.fromisoformat(as_of_date) if as_of_date else date.today()
        return svc.send_warning_digest(as_of_date=d)
    finally:
        db.close()


