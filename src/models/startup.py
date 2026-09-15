"""The core domain model.

Design notes:

* Raw and normalized values are both kept (``total_funding_raw`` next to
  ``total_funding_eur``) so a number can always be traced back to what a
  source literally said.
* ``funding_status`` is separate from the funding value. Unknown funding is
  *never* treated as "below the ceiling".
* ``dataset`` keeps fictional demo companies and real companies in strictly
  separate pools.
* ``human_overrides`` records every investor intervention, so a run can be
  reproduced and audited.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from .enums import (
    ConfidenceLevel,
    Dataset,
    EligibilityStatus,
    Recommendation,
    Stage,
    VerificationStatus,
)
from .scoring import EligibilityResult, RedFlag, ScoreBreakdown


def new_startup_id() -> str:
    return f"co_{uuid4().hex[:12]}"


class HumanOverride(BaseModel):
    """One investor intervention, stored forever."""

    field_name: str
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    author: str = "investor"


class Startup(BaseModel):
    # --- identity ---------------------------------------------------------
    id: str = Field(default_factory=new_startup_id)
    company_name: str
    normalized_name: str = ""
    website: str | None = None
    domain: str | None = None
    dataset: Dataset = Dataset.REAL

    # --- geography --------------------------------------------------------
    hq_country: str | None = None
    hq_country_raw: str | None = None
    city: str | None = None

    # --- basics -----------------------------------------------------------
    founded_year: int | None = None
    sector: str | None = None
    subsector: str | None = None
    themes: list[str] = Field(default_factory=list)
    stage: Stage = Stage.UNKNOWN
    stage_raw: str | None = None
    is_active: bool | None = None

    # --- funding ----------------------------------------------------------
    total_funding_eur: float | None = None
    total_funding_raw: str | None = None
    funding_status: VerificationStatus = VerificationStatus.MISSING
    last_round_eur: float | None = None
    last_round_raw: str | None = None
    last_round_date: date | None = None
    fx_note: str | None = None
    investors: list[str] = Field(default_factory=list)

    # --- people -----------------------------------------------------------
    founders: list[str] = Field(default_factory=list)
    founder_background: str | None = None

    # --- product & business ----------------------------------------------
    product_summary: str | None = None
    business_model: str | None = None
    customers: list[str] = Field(default_factory=list)
    traction_signals: list[str] = Field(default_factory=list)
    technology: str | None = None
    technical_moat: str | None = None
    competitors: list[str] = Field(default_factory=list)
    market_size_signal: str | None = None
    impact_signal: str | None = None
    why_now_signal: str | None = None

    # --- provenance & assessment -----------------------------------------
    source_urls: list[str] = Field(default_factory=list)
    data_confidence: ConfidenceLevel = ConfidenceLevel.UNVERIFIED
    eligibility_status: EligibilityStatus = EligibilityStatus.NOT_ASSESSED
    eligibility_reasons: list[str] = Field(default_factory=list)
    eligibility_result: EligibilityResult | None = None
    score_total: float | None = None
    score_breakdown: ScoreBreakdown | None = None
    red_flags: list[RedFlag] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)

    # --- human-in-the-loop ------------------------------------------------
    notes: str = ""
    investor_notes: list[str] = Field(default_factory=list)
    human_overrides: list[HumanOverride] = Field(default_factory=list)
    manual_eligibility_approved: bool = False
    shortlisted: bool = False
    recommendation: Recommendation | None = None

    # --- bookkeeping ------------------------------------------------------
    raw_record: dict[str, Any] = Field(default_factory=dict)
    source_adapter: str = "manual"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"use_enum_values": False}

    @field_validator("company_name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("company_name is required")
        return v.strip()

    # ------------------------------------------------------------------ #
    @property
    def is_demo(self) -> bool:
        return self.dataset == Dataset.DEMO

    @property
    def display_name(self) -> str:
        """Demo companies are marked, unless the name already says so."""
        if not self.is_demo or self.company_name.upper().startswith("DEMO"):
            return self.company_name
        return f"[DEMO] {self.company_name}"

    @property
    def red_flag_count(self) -> int:
        return len([f for f in self.red_flags if not f.dismissed_by_human])

    @property
    def is_rankable(self) -> bool:
        """Only eligible, or human-approved needs-review, companies get ranked."""
        return self.eligibility_status == EligibilityStatus.ELIGIBLE or (
            self.eligibility_status == EligibilityStatus.NEEDS_REVIEW
            and self.manual_eligibility_approved
        )

    def funding_display(self) -> str:
        if self.total_funding_eur is None:
            return "Unknown"
        return f"€{self.total_funding_eur:,.0f}"

    def record_override(self, field_name: str, new_value: Any, reason: str = "") -> None:
        old = getattr(self, field_name, None)
        self.human_overrides.append(
            HumanOverride(field_name=field_name, old_value=_jsonable(old),
                          new_value=_jsonable(new_value), reason=reason)
        )
        setattr(self, field_name, new_value)
        self.updated_at = datetime.now(timezone.utc)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return str(value)
