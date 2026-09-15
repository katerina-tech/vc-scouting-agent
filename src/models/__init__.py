"""Domain models for the VC Startup Scouting Agent."""

from .enums import (
    CheckOutcome,
    ClaimType,
    ConfidenceLevel,
    Dataset,
    EligibilityStatus,
    Recommendation,
    RedFlagSeverity,
    SourceTier,
    SourceType,
    Stage,
    Theme,
    VerificationStatus,
)
from .evidence import Evidence, FieldAssessment, level_from_score, new_id
from .scoring import (
    CriterionScore,
    EligibilityCheck,
    EligibilityResult,
    RedFlag,
    ScoreBreakdown,
)
from .startup import HumanOverride, Startup, new_startup_id
from .thesis import EUROPE_COUNTRIES, InvestmentThesis

__all__ = [
    "CheckOutcome",
    "ClaimType",
    "ConfidenceLevel",
    "CriterionScore",
    "Dataset",
    "EligibilityCheck",
    "EligibilityResult",
    "EligibilityStatus",
    "EUROPE_COUNTRIES",
    "Evidence",
    "FieldAssessment",
    "HumanOverride",
    "InvestmentThesis",
    "level_from_score",
    "new_id",
    "new_startup_id",
    "Recommendation",
    "RedFlag",
    "RedFlagSeverity",
    "ScoreBreakdown",
    "SourceTier",
    "SourceType",
    "Stage",
    "Startup",
    "Theme",
    "VerificationStatus",
]
