from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings
from app.core.logging import configure_logging


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise ValueError("invalid_time_format")
    h = int(parts[0])
    m = int(parts[1])
    if h < 0 or h > 23 or m < 0 or m > 59:
        raise ValueError("invalid_time_value")
    return h, m


def make_celery() -> Celery:
    settings = get_settings()
    configure_logging(settings.log_level)

    celery = Celery(
        "loadguard",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
        include=["app.workers.tasks"],
    )
    celery.conf.update(
        task_track_started=True,
        task_time_limit=60 * 15,
        task_soft_time_limit=60 * 14,
        worker_prefetch_multiplier=1,
        timezone=settings.scheduler_timezone,
        enable_utc=False,
    )

    am_h, am_m = _parse_hhmm(settings.run_am_time)
    pm_h, pm_m = _parse_hhmm(settings.run_pm_time)
    wd_h, wd_m = _parse_hhmm(settings.warning_digest_time)

    celery.conf.beat_schedule = {
        "evaluate_am_0900": {
            "task": "detection.evaluate_run",
            "schedule": crontab(hour=am_h, minute=am_m),
            "args": ("AM_0900",),
        },
        "evaluate_pm_1400": {
            "task": "detection.evaluate_run",
            "schedule": crontab(hour=pm_h, minute=pm_m),
            "args": ("PM_1400",),
        },
        "warning_digest": {
            "task": "notifications.send_warning_digest",
            "schedule": crontab(hour=wd_h, minute=wd_m),
            "args": (),
        },
    }
    return celery


celery_app = make_celery()


