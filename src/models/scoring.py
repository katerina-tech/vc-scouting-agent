"""Scoring, red-flag and eligibility result models.

A score is never a bare number here. Every criterion carries the rating, the
weight, the arithmetic, the reasoning, the evidence it rests on, and how
confident the system is. A criterion with no evidence stays ``None`` — it is
never silently rated 0 or 3.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from .enums import (
    CheckOutcome,
    ConfidenceLevel,
    EligibilityStatus,
    RedFlagSeverity,
)

ScoreSource = Literal["deterministic", "llm", "human_override"]


class CriterionScore(BaseModel):
    """One of the eight scoring criteria, fully explained."""

    criterion: str
    label: str
    raw_rating: int | None = Field(default=None, ge=0, le=5)
    weight: float
    reasoning: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: ScoreSource = "deterministic"
    evidence_missing: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def weighted_score(self) -> float:
        """raw_rating / 5 * weight — or 0.0 when there is nothing to rate."""
        if self.raw_rating is None:
            return 0.0
        return round(self.raw_rating / 5 * self.weight, 2)

    @property
    def is_scored(self) -> bool:
        return self.raw_rating is not None

    @property
    def display_rating(self) -> str:
        if self.raw_rating is None:
            return "— (no evidence)"
        return f"{self.raw_rating}/5"


class ScoreBreakdown(BaseModel):
    """The full 100-point picture, including how much of it could be assessed."""

    criteria: list[CriterionScore] = Field(default_factory=list)
    scored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    engine_version: str = "1.0"
    notes: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score_total(self) -> float:
        return round(sum(c.weighted_score for c in self.criteria), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def assessable_weight(self) -> float:
        """Sum of weights for criteria that actually had evidence to rate."""
        return round(sum(c.weight for c in self.criteria if c.is_scored), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_weight(self) -> float:
        return round(sum(c.weight for c in self.criteria), 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def evidence_coverage(self) -> float:
        """Share of the 100 points that could be assessed at all (0..1)."""
        if not self.total_weight:
            return 0.0
        return round(self.assessable_weight / self.total_weight, 3)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def confidence(self) -> float:
        """Weight-averaged confidence across the criteria that were scored."""
        scored = [c for c in self.criteria if c.is_scored]
        if not scored:
            return 0.0
        total_w = sum(c.weight for c in scored) or 1.0
        return round(sum(c.confidence * c.weight for c in scored) / total_w, 3)

    @property
    def confidence_level(self) -> ConfidenceLevel:
        from .evidence import level_from_score

        return level_from_score(self.confidence)

    @property
    def unscored_criteria(self) -> list[CriterionScore]:
        return [c for c in self.criteria if not c.is_scored]

    def get(self, criterion: str) -> CriterionScore | None:
        for c in self.criteria:
            if c.criterion == criterion:
                return c
        return None

    def score_for(self, criterion: str) -> float:
        c = self.get(criterion)
        return c.weighted_score if c else 0.0


class RedFlag(BaseModel):
    """Shown to the investor, never used to silently reject a company."""

    code: str
    title: str
    detail: str = ""
    severity: RedFlagSeverity = RedFlagSeverity.MEDIUM
    evidence_ids: list[str] = Field(default_factory=list)
    source: ScoreSource = "deterministic"
    dismissed_by_human: bool = False

    @property
    def display(self) -> str:
        return f"{self.severity.label} {self.title}"


class EligibilityCheck(BaseModel):
    """One deterministic hard filter and why it came out the way it did."""

    check: str
    label: str
    outcome: CheckOutcome
    detail: str = ""
    evidence_ids: list[str] = Field(default_factory=list)

    @property
    def display(self) -> str:
        marker = {"PASS": "Pass", "FAIL": "Fail", "UNKNOWN": "Unresolved"}[self.outcome.value]
        return f"**{marker}** — {self.label}: {self.detail}" if self.detail \
            else f"**{marker}** — {self.label}"


class EligibilityResult(BaseModel):
    status: EligibilityStatus = EligibilityStatus.NOT_ASSESSED
    checks: list[EligibilityCheck] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    assessed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def failed(self) -> list[EligibilityCheck]:
        return [c for c in self.checks if c.outcome == CheckOutcome.FAIL]

    @property
    def unknown(self) -> list[EligibilityCheck]:
        return [c for c in self.checks if c.outcome == CheckOutcome.UNKNOWN]
