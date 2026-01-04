from __future__ import annotations

from enum import Enum


class LoadSource(str, Enum):
    API = "API"
    FTP = "FTP"


class VersionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class RunType(str, Enum):
    AM_0900 = "AM_0900"
    PM_1400 = "PM_1400"
    MANUAL = "MANUAL"
    REPLAY_AS_OF = "REPLAY_AS_OF"
    REPLAY_LATEST = "REPLAY_LATEST"


class Severity(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DetectionLayer(str, Enum):
    DSL = "DSL"
    STATS = "STATS"
    ML = "ML"


class LlmStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class NotificationChannel(str, Enum):
    EMAIL = "EMAIL"


class ShiftRule(str, Enum):
    NONE = "NONE"
    NEXT_BUSINESS_DAY = "NEXT_BUSINESS_DAY"
    PREV_BUSINESS_DAY = "PREV_BUSINESS_DAY"
    NEAREST_BUSINESS_DAY = "NEAREST_BUSINESS_DAY"


