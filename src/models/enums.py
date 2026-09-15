"""Controlled vocabularies used across the whole application.

Keeping these as enums (rather than free strings) is what makes the pipeline
auditable: a company is never "sort of eligible", and a claim is never "sort
of verified".
"""

from __future__ import annotations

from enum import Enum


class VerificationStatus(str, Enum):
    """How a single field's value came to be. Never blur these together."""

    VERIFIED = "VERIFIED"      # backed by a credible external source
    INFERRED = "INFERRED"      # derived by the system or the LLM from other text
    UNVERIFIED = "UNVERIFIED"  # a value exists but nothing backs it up
    MISSING = "MISSING"        # no value at all

    @property
    def label(self) -> str:
        return {
            "VERIFIED": "Verified",
            "INFERRED": "Inferred",
            "UNVERIFIED": "Unverified",
            "MISSING": "Missing",
        }[self.value]


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"              # multiple reliable sources agree
    MEDIUM = "MEDIUM"          # one credible source, or several weaker ones
    LOW = "LOW"                # indirect evidence or inference
    UNVERIFIED = "UNVERIFIED"  # no reliable evidence at all

    @property
    def label(self) -> str:
        return {
            "HIGH": "High",
            "MEDIUM": "Medium",
            "LOW": "Low",
            "UNVERIFIED": "Unverified",
        }[self.value]

    @property
    def numeric(self) -> float:
        return {"HIGH": 0.9, "MEDIUM": 0.65, "LOW": 0.35, "UNVERIFIED": 0.1}[self.value]


class SourceTier(str, Enum):
    """Source quality hierarchy. Tier 1 is strongest."""

    TIER_1 = "TIER_1"  # official company / investor / regulatory
    TIER_2 = "TIER_2"  # reputable business media, established databases
    TIER_3 = "TIER_3"  # LinkedIn, directories, accelerator pages
    TIER_4 = "TIER_4"  # blogs, unverified aggregators
    NONE = "NONE"      # no external source (user input or model inference)

    @property
    def base_confidence(self) -> float:
        return {
            "TIER_1": 0.92,
            "TIER_2": 0.75,
            "TIER_3": 0.5,
            "TIER_4": 0.3,
            "NONE": 0.15,
        }[self.value]

    @property
    def label(self) -> str:
        return {
            "TIER_1": "Tier 1 — official / regulatory",
            "TIER_2": "Tier 2 — reputable media / database",
            "TIER_3": "Tier 3 — LinkedIn / directory",
            "TIER_4": "Tier 4 — blog / aggregator",
            "NONE": "No external source",
        }[self.value]


class SourceType(str, Enum):
    COMPANY_WEBSITE = "COMPANY_WEBSITE"
    FUNDING_ANNOUNCEMENT = "FUNDING_ANNOUNCEMENT"
    INVESTOR_ANNOUNCEMENT = "INVESTOR_ANNOUNCEMENT"
    REGULATORY_RECORD = "REGULATORY_RECORD"
    BUSINESS_MEDIA = "BUSINESS_MEDIA"
    STARTUP_DATABASE = "STARTUP_DATABASE"
    LINKEDIN = "LINKEDIN"
    STARTUP_DIRECTORY = "STARTUP_DIRECTORY"
    ACCELERATOR_PAGE = "ACCELERATOR_PAGE"
    BLOG = "BLOG"
    AGGREGATOR = "AGGREGATOR"
    USER_INPUT = "USER_INPUT"
    LLM_INFERENCE = "LLM_INFERENCE"
    OTHER = "OTHER"

    @property
    def tier(self) -> SourceTier:
        return _SOURCE_TYPE_TIERS[self]


_SOURCE_TYPE_TIERS: dict[SourceType, SourceTier] = {
    SourceType.COMPANY_WEBSITE: SourceTier.TIER_1,
    SourceType.FUNDING_ANNOUNCEMENT: SourceTier.TIER_1,
    SourceType.INVESTOR_ANNOUNCEMENT: SourceTier.TIER_1,
    SourceType.REGULATORY_RECORD: SourceTier.TIER_1,
    SourceType.BUSINESS_MEDIA: SourceTier.TIER_2,
    SourceType.STARTUP_DATABASE: SourceTier.TIER_2,
    SourceType.LINKEDIN: SourceTier.TIER_3,
    SourceType.STARTUP_DIRECTORY: SourceTier.TIER_3,
    SourceType.ACCELERATOR_PAGE: SourceTier.TIER_3,
    SourceType.BLOG: SourceTier.TIER_4,
    SourceType.AGGREGATOR: SourceTier.TIER_4,
    SourceType.USER_INPUT: SourceTier.NONE,
    SourceType.LLM_INFERENCE: SourceTier.NONE,
    SourceType.OTHER: SourceTier.TIER_4,
}


class Stage(str, Enum):
    PRE_SEED = "PRE_SEED"
    SEED = "SEED"
    SERIES_A = "SERIES_A"
    SERIES_B_PLUS = "SERIES_B_PLUS"
    GRANT_FUNDED = "GRANT_FUNDED"
    BOOTSTRAPPED = "BOOTSTRAPPED"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return {
            "PRE_SEED": "Pre-Seed",
            "SEED": "Seed",
            "SERIES_A": "Series A",
            "SERIES_B_PLUS": "Series B+",
            "GRANT_FUNDED": "Grant-funded",
            "BOOTSTRAPPED": "Bootstrapped",
            "UNKNOWN": "Unknown",
        }[self.value]


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INELIGIBLE = "INELIGIBLE"
    NOT_ASSESSED = "NOT_ASSESSED"

    @property
    def label(self) -> str:
        return {
            "ELIGIBLE": "Eligible",
            "NEEDS_REVIEW": "Needs review",
            "INELIGIBLE": "Ineligible",
            "NOT_ASSESSED": "Not assessed",
        }[self.value]


class CheckOutcome(str, Enum):
    """Outcome of a single deterministic eligibility check."""

    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class ClaimType(str, Enum):
    """Every LLM statement must be labelled with one of these."""

    FACT = "FACT"
    INFERENCE = "INFERENCE"
    OPINION = "OPINION"
    UNKNOWN = "UNKNOWN"


class Recommendation(str, Enum):
    """Deliberately excludes an automatic INVEST. That call stays human."""

    PASS_ = "PASS"
    WATCH = "WATCH"
    INVESTIGATE = "INVESTIGATE"

    @property
    def label(self) -> str:
        return {
            "PASS": "PASS — do not pursue now",
            "WATCH": "WATCH — revisit later",
            "INVESTIGATE": "INVESTIGATE — worth a diligence conversation",
        }[self.value]


class RedFlagSeverity(str, Enum):
    INFO = "INFO"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def label(self) -> str:
        return {"INFO": "Info", "MEDIUM": "Medium", "HIGH": "High"}[self.value]


class Dataset(str, Enum):
    """Demo and real companies live in separate, never-mixed datasets."""

    DEMO = "DEMO"
    REAL = "REAL"

    @property
    def label(self) -> str:
        return {"DEMO": "Demo data (fictional)", "REAL": "Real companies"}[self.value]


class Theme(str, Enum):
    """Default thesis themes. Custom themes are supported as free strings."""

    CLIMATE = "Climate"
    HEALTH = "Health"
    ECONOMIC_EMPOWERMENT = "Economic Empowerment"
    OTHER = "Other"
