"""The evidence model — the backbone of the whole application.

Rule of the system: **no important field is displayed without the evidence
behind it**. An LLM inference is a first-class citizen here, but it is stored
with ``source_type = LLM_INFERENCE`` and can never be labelled VERIFIED.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from .enums import ConfidenceLevel, SourceTier, SourceType, VerificationStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str = "ev") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class Evidence(BaseModel):
    """One factual claim about one field of one startup, with its provenance."""

    id: str = Field(default_factory=lambda: new_id("ev"))
    startup_id: str
    field_name: str
    value: Any = None

    source_url: str | None = None
    source_title: str | None = None
    source_type: SourceType = SourceType.OTHER
    source_tier: SourceTier | None = None

    retrieved_at: datetime = Field(default_factory=_now)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel | None = None
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED

    evidence_note: str = ""
    human_verified: bool = False
    added_by: str = "system"

    model_config = {"use_enum_values": False}

    @field_validator("field_name")
    @classmethod
    def _field_name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field_name is required for every piece of evidence")
        return v.strip()

    @model_validator(mode="after")
    def _derive(self) -> "Evidence":
        # Tier follows from the source type unless explicitly overridden.
        if self.source_tier is None:
            object.__setattr__(self, "source_tier", self.source_type.tier)

        # When the caller did not state a confidence, derive it from source
        # quality — that is the whole point of the tier hierarchy.
        if "confidence" not in self.model_fields_set:
            base = self.source_tier.base_confidence
            if not self.source_url and self.source_type != SourceType.USER_INPUT:
                # A claim with no link is worth less than the same claim with one.
                base = min(base, 0.4)
            if self.verification_status == VerificationStatus.INFERRED:
                base = min(base, 0.45)
            elif self.verification_status == VerificationStatus.MISSING:
                base = 0.0
            object.__setattr__(self, "confidence", round(base, 3))

        # An LLM inference or bare user input can never be VERIFIED by itself.
        if (
            self.source_type in (SourceType.LLM_INFERENCE,)
            and self.verification_status == VerificationStatus.VERIFIED
            and not self.human_verified
        ):
            object.__setattr__(self, "verification_status", VerificationStatus.INFERRED)

        # A human ticking "verified" is authoritative and pins confidence high.
        if self.human_verified:
            object.__setattr__(self, "verification_status", VerificationStatus.VERIFIED)
            object.__setattr__(self, "confidence", max(self.confidence, 0.95))

        if self.confidence_level is None:
            object.__setattr__(self, "confidence_level", level_from_score(self.confidence))
        return self

    @property
    def is_supporting(self) -> bool:
        """Whether this evidence can support a VERIFIED status on its own."""
        return self.human_verified or (
            self.source_tier in (SourceTier.TIER_1, SourceTier.TIER_2)
            and bool(self.source_url)
        )

    def display_source(self) -> str:
        title = self.source_title or self.source_url or "No source recorded"
        return f"{title} ({self.source_tier.label if self.source_tier else 'unknown tier'})"


def level_from_score(score: float) -> ConfidenceLevel:
    if score >= 0.8:
        return ConfidenceLevel.HIGH
    if score >= 0.55:
        return ConfidenceLevel.MEDIUM
    if score >= 0.25:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNVERIFIED


class FieldAssessment(BaseModel):
    """What the UI shows next to a value: status, confidence and its sources."""

    field_name: str
    value: Any = None
    verification_status: VerificationStatus = VerificationStatus.MISSING
    confidence: float = 0.0
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNVERIFIED
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    note: str = ""

    @property
    def has_value(self) -> bool:
        if self.value is None:
            return False
        if isinstance(self.value, str):
            return bool(self.value.strip())
        if isinstance(self.value, (list, tuple, dict, set)):
            return len(self.value) > 0
        return True
