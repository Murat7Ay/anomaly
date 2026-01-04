from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.profile.config import InstitutionProfileConfig
from app.infra.llm.client import OnPremLlmClient
from app.infra.repositories.evaluation_repo import EvaluationRepository
from app.infra.repositories.llm_repo import LlmExplanationRepository
from app.infra.repositories.profile_repo import ProfileRepository

log = get_logger(__name__)


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class LlmExplainerService:
    """
    Creates and persists an auditable LLM explanation for a DailyEvaluation.

    No decision authority: the LLM only summarizes and explains the already-persisted decision.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = get_settings()
        self._eval_repo = EvaluationRepository(db)
        self._profile_repo = ProfileRepository(db)
        self._llm_repo = LlmExplanationRepository(db)
        self._client = OnPremLlmClient()

    def explain_evaluation(self, *, evaluation_id: uuid.UUID) -> dict[str, Any]:
        existing = self._llm_repo.get_for_evaluation(evaluation_id)
        if existing and existing.status.value in {"SUCCESS", "FAILED"}:
            return {"status": existing.status.value, "llm_explanation_id": str(existing.id)}

        ev = self._eval_repo.get_by_id(evaluation_id)
        if not ev:
            raise ValueError("evaluation_not_found")

        profile_v = self._profile_repo.get_version(ev.profile_config_version_id)
        profile = InstitutionProfileConfig.model_validate(profile_v.config_json)

        prompt_json = self._build_prompt_json(ev=ev, profile=profile)
        prompt_text = self._build_prompt_text(prompt_json)

        row = existing
        if row is None:
            row = self._llm_repo.create_requested(
                evaluation_id=evaluation_id,
                model_name=self._settings.llm_model_name,
                requested_at_utc=utc_now(),
                prompt_json=prompt_json,
                prompt_text=prompt_text,
            )

        try:
            resp = self._client.generate(prompt_text=prompt_text)
            self._llm_repo.mark_success(
                explanation_id=row.id,
                completed_at_utc=utc_now(),
                response_text=resp.text,
                response_json=resp.raw_json,
            )
            return {"status": "SUCCESS", "llm_explanation_id": str(row.id)}
        except Exception as e:
            log.error("llm_call_failed", evaluation_id=str(evaluation_id), error=str(e))
            self._llm_repo.mark_failed(
                explanation_id=row.id,
                completed_at_utc=utc_now(),
                error_text=str(e),
                response_json=None,
            )
            return {"status": "FAILED", "llm_explanation_id": str(row.id), "error": str(e)}

    def _build_prompt_json(self, *, ev, profile: InstitutionProfileConfig) -> dict[str, Any]:
        profile_summary = {
            "timezone": profile.timezone,
            "calendar_id": str(profile.calendar_id),
            "maturity_policy": profile.maturity_policy.model_dump(mode="json"),
            "schedule": profile.schedule.model_dump(mode="json"),
            "volume_models": [vm.model_dump(mode="json") for vm in profile.volume_models],
        }

        return {
            "instructions": {
                "role": "explanation_only",
                "must_not_change_decision": True,
                "output_format": {
                    "summary": "1-2 sentences",
                    "reasons": "bulleted list",
                    "suggestions": "bulleted list (DSL/profile tuning ideas)",
                },
            },
            "evaluation": {
                "evaluation_id": str(ev.id),
                "institution_id": str(ev.institution_id),
                "as_of_date": ev.as_of_date.isoformat(),
                "run_type": ev.run_type.value if hasattr(ev.run_type, "value") else str(ev.run_type),
                "run_at_utc": ev.run_at_utc.isoformat(),
                "is_anomaly": bool(ev.is_anomaly),
                "final_severity": ev.final_severity.value if hasattr(ev.final_severity, "value") else str(ev.final_severity),
                "anomaly_types": list(ev.anomaly_types),
                "calendar_context": ev.calendar_context_json,
                "input_aggregate": ev.input_aggregate_json,
                "layer_results": ev.layer_results_json,
            },
            "profile_summary": profile_summary,
        }

    def _build_prompt_text(self, prompt_json: dict[str, Any]) -> str:
        payload = json.dumps(prompt_json, ensure_ascii=False, sort_keys=True, indent=2)
        return (
            "Explain the evaluation deterministically and concisely.\n"
            "Rules:\n"
            "- Do NOT change the system decision.\n"
            "- Refer to concrete thresholds/scores that were applied.\n"
            "- If no anomaly: explain why it is considered normal.\n"
            "- Provide 2-5 suggestions to reduce future false positives via DSL/Profile tuning.\n"
            "\n"
            "INPUT_JSON:\n"
            f"{payload}\n"
        )


