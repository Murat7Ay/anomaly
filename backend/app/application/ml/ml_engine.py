from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping

import numpy as np
from dateutil.relativedelta import relativedelta
from scipy.stats import chi2
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.application.calendar_service import CalendarService, CalendarWindow
from app.domain.profile.config import InstitutionProfileConfig
from app.domain.profile.schedule_resolver import ScheduleResolver
from app.infra.repositories.load_repo import LoadRepository
from app.infra.repositories.ml_repo import MlArtifactRepository


class MlInsufficientDataError(Exception):
    pass


@dataclass(frozen=True)
class MlSignal:
    layer: str  # "ML"
    signal_type: str  # e.g. PATTERN_BREAK
    is_triggered: bool
    severity_suggested: str  # WARNING|CRITICAL
    score: Decimal | None
    threshold_high: Decimal | None
    explanation_json: dict[str, Any]


class MlEngineV1:
    """
    Deterministic unsupervised ML scorer using robust scaling + Mahalanobis distance.

    - No supervised learning.
    - Produces a single combined anomaly score across volume + timing features.
    - Persists per-institution per-day artifacts for audit/replay.
    """

    ALGORITHM_VERSION = "ml_mahalanobis_v1"

    def __init__(
        self,
        db: Session,
        *,
        calendar_service: CalendarService,
        schedule_resolver: ScheduleResolver,
        load_repo: LoadRepository | None = None,
        artifact_repo: MlArtifactRepository | None = None,
    ) -> None:
        self._db = db
        self._cal = calendar_service
        self._resolver = schedule_resolver
        self._load_repo = load_repo or LoadRepository(db)
        self._artifact_repo = artifact_repo or MlArtifactRepository(db)

    def evaluate(
        self,
        *,
        institution_id: uuid.UUID,
        profile_config_version_id: uuid.UUID,
        profile: InstitutionProfileConfig,
        as_of_date: date,
        run_type: str,
        daily_aggregate: Mapping[str, Any],
        calendar_window: CalendarWindow,
        stats_signals: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        # Only evaluate on expected days (any run) and only when we have data and timing.
        expected_by_date = self._resolver.expected_by_date(
            schedule=profile.schedule, window=calendar_window, start_date=as_of_date, end_date=as_of_date
        )
        if as_of_date not in expected_by_date:
            return []

        if not daily_aggregate.get("has_load") or daily_aggregate.get("earliest_received_minutes") is None:
            return []

        # Build or reuse artifact for this (institution, as_of_date, profile_version).
        artifact = self._artifact_repo.get(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_config_version_id,
            algorithm_version=self.ALGORITHM_VERSION,
        )
        if artifact is None:
            artifact = self._compute_and_persist_artifact(
                institution_id=institution_id,
                as_of_date=as_of_date,
                profile_config_version_id=profile_config_version_id,
                profile=profile,
            )

        model = artifact.artifact_json
        feature_names: list[str] = model["feature_names"]
        median = np.array(model["median"], dtype=float)
        scale = np.array(model["scale"], dtype=float)
        cov_inv = np.array(model["cov_inv"], dtype=float)
        df = int(model["df"])
        threshold = float(model["threshold"])

        x = self._current_feature_vector(profile=profile, daily_aggregate=daily_aggregate, feature_names=feature_names)
        if x is None:
            return []
        z = (x - median) / scale
        d2 = float(z.T @ cov_inv @ z)

        triggered = d2 > threshold
        # Confidence: ratio to threshold capped at 1.0+
        confidence = min(1.0, d2 / threshold) if threshold > 0 else 1.0

        # Contributions (proxy): absolute standardized feature values
        contrib = [{"feature": feature_names[i], "abs_z": float(abs(z[i])), "z": float(z[i])} for i in range(len(z))]
        contrib.sort(key=lambda c: c["abs_z"], reverse=True)
        top = contrib[:5]

        severity = "CRITICAL" if triggered and confidence >= 1.25 else "WARNING"

        if not triggered:
            return []

        return [
            {
                "layer": "ML",
                "signal_type": "PATTERN_BREAK",
                "metric_id": None,
                "occurrence_id": None,
                "is_triggered": True,
                "severity_suggested": severity,
                "score": Decimal(str(confidence)),
                "threshold_low": None,
                "threshold_high": Decimal(str(threshold)),
                "explanation_json": {
                    "algorithm_version": self.ALGORITHM_VERSION,
                    "artifact_id": str(artifact.id),
                    "artifact_hash": artifact.artifact_hash,
                    "df": df,
                    "distance_squared": d2,
                    "threshold": threshold,
                    "confidence": confidence,
                    "top_feature_contributions": top,
                    "stats_signals_present": [s.get("signal_type") for s in stats_signals if s.get("is_triggered")],
                },
            }
        ]

    def _compute_and_persist_artifact(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        profile_config_version_id: uuid.UUID,
        profile: InstitutionProfileConfig,
    ):
        # Training window: last 12 months, excluding as_of_date.
        start = as_of_date - relativedelta(months=12)
        end_excl = as_of_date

        # Calendar window for shifting and expected-day filtering
        window = self._cal.build_window_for_range(
            calendar_id=profile.calendar_id,
            start_date=start - timedelta(days=60),
            end_date=end_excl + timedelta(days=60),
        )

        expected_by_date = self._resolver.expected_by_date(
            schedule=profile.schedule, window=window, start_date=start, end_date=end_excl - timedelta(days=1)
        )
        expected_dates = set(expected_by_date.keys())

        loads = self._load_repo.list_by_local_date_range(
            institution_id=institution_id,
            start_date=start,
            end_date_exclusive=end_excl,
        )
        tz = ZoneInfo(profile.timezone)
        daily = self._aggregate_for_range(loads=loads, tz=tz)

        # Feature spec: all profile volume metrics + arrival minutes
        feature_names = [f"log1p::{vm.metric_id}" for vm in profile.volume_models] + ["arrival_minutes"]

        X: list[np.ndarray] = []
        for d in sorted(expected_dates):
            agg = daily.get(d)
            if not agg:
                continue
            if agg.get("earliest_minutes") is None:
                continue
            vec = self._feature_vector_from_agg(profile=profile, agg=agg, feature_names=feature_names)
            if vec is None:
                continue
            X.append(vec)

        min_n = int(profile.maturity_policy.min_expected_loads_for_ml)
        if len(X) < min_n:
            raise MlInsufficientDataError(f"ml_insufficient_samples:{len(X)}<{min_n}")

        Xmat = np.vstack(X)
        # Robust scaling via median + MAD
        med = np.median(Xmat, axis=0)
        mad = np.median(np.abs(Xmat - med), axis=0)
        scale = 1.4826 * mad
        # Fallback to std if MAD is 0
        std = np.std(Xmat, axis=0, ddof=1)
        scale = np.where(scale == 0, np.where(std == 0, 1.0, std), scale)

        Z = (Xmat - med) / scale
        cov = np.cov(Z, rowvar=False)
        # Regularize to ensure invertibility
        cov = cov + np.eye(cov.shape[0]) * 1e-3
        cov_inv = np.linalg.inv(cov)

        df = int(Z.shape[1])
        threshold = float(chi2.ppf(0.99, df=df))

        artifact_json = {
            "algorithm_version": self.ALGORITHM_VERSION,
            "as_of_date": as_of_date.isoformat(),
            "train_start_date": start.isoformat(),
            "train_end_exclusive": end_excl.isoformat(),
            "train_n": int(Z.shape[0]),
            "feature_names": feature_names,
            "median": med.tolist(),
            "scale": scale.tolist(),
            "cov_inv": cov_inv.tolist(),
            "df": df,
            "threshold": threshold,
        }
        artifact_hash = hashlib.sha256(
            json.dumps(artifact_json, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return self._artifact_repo.upsert(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_config_version_id,
            algorithm_version=self.ALGORITHM_VERSION,
            artifact_hash=artifact_hash,
            artifact_json=artifact_json,
        )

    def _aggregate_for_range(self, *, loads, tz: ZoneInfo) -> dict[date, dict[str, Any]]:
        daily: dict[date, dict[str, Any]] = {}
        for lb in loads:
            d = lb.institution_local_date
            b = daily.setdefault(d, {"metrics": {}, "earliest_minutes": None})

            if lb.debt_item_count is not None:
                b["metrics"]["debt_item_count"] = b["metrics"].get("debt_item_count", Decimal(0)) + Decimal(int(lb.debt_item_count))
            if lb.total_debt_amount is not None:
                b["metrics"]["total_debt_amount"] = b["metrics"].get("total_debt_amount", Decimal(0)) + Decimal(lb.total_debt_amount)
            if lb.unique_customer_count is not None:
                v = Decimal(int(lb.unique_customer_count))
                cur = b["metrics"].get("unique_customer_count")
                b["metrics"]["unique_customer_count"] = v if cur is None else max(cur, v)

            if isinstance(lb.metrics_json, dict):
                for k, raw_v in lb.metrics_json.items():
                    try:
                        dv = Decimal(str(raw_v))
                    except Exception:
                        continue
                    b["metrics"][k] = b["metrics"].get(k, Decimal(0)) + dv

            if lb.received_at_utc is not None:
                local_dt = lb.received_at_utc.astimezone(tz)
                m = local_dt.hour * 60 + local_dt.minute
                b["earliest_minutes"] = m if b["earliest_minutes"] is None else min(b["earliest_minutes"], m)
        return daily

    def _feature_vector_from_agg(
        self, *, profile: InstitutionProfileConfig, agg: dict[str, Any], feature_names: list[str]
    ) -> np.ndarray | None:
        import math

        feats: list[float] = []
        metrics: Mapping[str, Decimal] = agg["metrics"]
        for vm in profile.volume_models:
            v = metrics.get(vm.metric_id)
            if v is None:
                return None
            fv = float(v)
            feats.append(math.log1p(max(fv, 0.0)))
        feats.append(float(agg["earliest_minutes"]))
        return np.array(feats, dtype=float)

    def _current_feature_vector(
        self, *, profile: InstitutionProfileConfig, daily_aggregate: Mapping[str, Any], feature_names: list[str]
    ) -> np.ndarray | None:
        import math

        metrics: Mapping[str, Decimal] = daily_aggregate.get("metrics", {})
        feats: list[float] = []
        for vm in profile.volume_models:
            v = metrics.get(vm.metric_id)
            if v is None:
                return None
            feats.append(math.log1p(max(float(v), 0.0)))
        if daily_aggregate.get("earliest_received_minutes") is None:
            return None
        feats.append(float(daily_aggregate.get("earliest_received_minutes")))
        return np.array(feats, dtype=float)


