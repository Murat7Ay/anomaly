from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from loadguard.api.deps import DB, CurrentUser, require_roles
from loadguard.services import governance
from loadguard.services.common import verify_audit_chain

router = APIRouter(tags=["governance"])
OVERSIGHT = require_roles("APPROVER", "ADMIN")


@router.get("/system/status")
def system_status(s: DB, _: CurrentUser) -> dict[str, Any]:
    return governance.system_status(s)


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
def metrics(s: DB) -> str:
    """Aggregate counters only (no personal data). Expose on the internal network to Prometheus."""
    return governance.prometheus_metrics(s)


@router.get("/evaluations/{evaluation_id}")
def evaluation_dossier(evaluation_id: uuid.UUID, s: DB, _: CurrentUser) -> dict[str, Any]:
    """Everything needed to explain a decision years later: exact inputs, versions and output."""
    return governance.evaluation_dossier(s, evaluation_id)


@router.post("/evaluations/{evaluation_id}/verify")
def verify_evaluation(evaluation_id: uuid.UUID, s: DB, _: CurrentUser) -> dict[str, Any]:
    return governance.verify_evaluation(s, evaluation_id)


@router.post("/governance/verify-sample", dependencies=[OVERSIGHT])
def verify_sample(s: DB, n: int = Query(default=200, ge=1, le=5000)) -> dict[str, Any]:
    return governance.verify_sample(s, n)


@router.get("/governance/audit-chain", dependencies=[OVERSIGHT])
def audit_chain(s: DB) -> dict[str, Any]:
    return verify_audit_chain(s)


@router.get("/insights/shadow")
def shadow(s: DB, _: CurrentUser, days: int = Query(default=120, ge=7, le=730)) -> list[dict[str, Any]]:
    return governance.shadow_report(s, days)
