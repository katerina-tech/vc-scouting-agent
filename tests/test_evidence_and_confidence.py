"""Evidence, confidence assignment and the source-quality hierarchy."""

from __future__ import annotations

import pytest

from src.models.enums import ConfidenceLevel, SourceTier, SourceType, VerificationStatus
from src.models.evidence import Evidence
from src.research.confidence import assess_field, values_agree
from src.research.evidence_manager import EvidenceManager
from tests.conftest import make_startup


def ev(startup, **overrides) -> Evidence:
    defaults = dict(
        startup_id=startup.id,
        field_name="total_funding_eur",
        value=1_800_000,
        source_url="https://press.example/a",
        source_type=SourceType.FUNDING_ANNOUNCEMENT,
        verification_status=VerificationStatus.VERIFIED,
    )
    defaults.update(overrides)
    return Evidence(**defaults)


# ------------------------------------------------------- source hierarchy
@pytest.mark.parametrize(
    "source_type, expected_tier",
    [
        (SourceType.COMPANY_WEBSITE, SourceTier.TIER_1),
        (SourceType.FUNDING_ANNOUNCEMENT, SourceTier.TIER_1),
        (SourceType.REGULATORY_RECORD, SourceTier.TIER_1),
        (SourceType.BUSINESS_MEDIA, SourceTier.TIER_2),
        (SourceType.STARTUP_DATABASE, SourceTier.TIER_2),
        (SourceType.LINKEDIN, SourceTier.TIER_3),
        (SourceType.ACCELERATOR_PAGE, SourceTier.TIER_3),
        (SourceType.BLOG, SourceTier.TIER_4),
        (SourceType.AGGREGATOR, SourceTier.TIER_4),
    ],
)
def test_source_types_map_to_the_documented_tiers(source_type, expected_tier):
    assert source_type.tier == expected_tier


def test_tier_one_outranks_tier_four_in_confidence():
    assert SourceTier.TIER_1.base_confidence > SourceTier.TIER_2.base_confidence
    assert SourceTier.TIER_2.base_confidence > SourceTier.TIER_3.base_confidence
    assert SourceTier.TIER_3.base_confidence > SourceTier.TIER_4.base_confidence


def test_confidence_is_derived_from_the_tier_when_not_supplied():
    startup = make_startup()
    strong = ev(startup, source_type=SourceType.FUNDING_ANNOUNCEMENT)
    weak = ev(startup, source_type=SourceType.BLOG, source_url="https://blog.example/x")
    assert strong.confidence > weak.confidence


def test_an_llm_inference_can_never_call_itself_verified():
    startup = make_startup()
    inference = ev(
        startup, source_type=SourceType.LLM_INFERENCE, source_url=None,
        verification_status=VerificationStatus.VERIFIED,
    )
    assert inference.verification_status == VerificationStatus.INFERRED


def test_a_human_tick_pins_the_field_verified_and_confident():
    startup = make_startup()
    checked = ev(startup, source_type=SourceType.BLOG, human_verified=True)
    assert checked.verification_status == VerificationStatus.VERIFIED
    assert checked.confidence >= 0.95


# ------------------------------------------------------ confidence levels
def test_two_agreeing_credible_sources_give_high_confidence():
    startup = make_startup()
    evidences = [
        ev(startup, source_url="https://press.example/a"),
        ev(startup, source_url="https://media.example/b", source_type=SourceType.BUSINESS_MEDIA),
    ]
    assessment = assess_field("total_funding_eur", 1_800_000, evidences)
    assert assessment.confidence_level == ConfidenceLevel.HIGH
    assert assessment.verification_status == VerificationStatus.VERIFIED


def test_one_credible_source_gives_medium_or_better():
    startup = make_startup()
    assessment = assess_field("total_funding_eur", 1_800_000, [ev(startup)])
    assert assessment.confidence_level in (ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)


def test_inference_only_gives_low_confidence():
    startup = make_startup()
    inference = ev(
        startup, source_type=SourceType.LLM_INFERENCE, source_url=None,
        verification_status=VerificationStatus.INFERRED,
    )
    assessment = assess_field("total_funding_eur", 1_800_000, [inference])
    assert assessment.confidence_level in (ConfidenceLevel.LOW, ConfidenceLevel.UNVERIFIED)
    assert assessment.verification_status == VerificationStatus.INFERRED


def test_no_evidence_means_unverified_or_missing():
    with_value = assess_field("total_funding_eur", 1_800_000, [])
    without_value = assess_field("total_funding_eur", None, [])
    assert with_value.verification_status == VerificationStatus.UNVERIFIED
    assert without_value.verification_status == VerificationStatus.MISSING
    assert without_value.confidence == 0.0


# --------------------------------------------------------------- conflicts
def test_disagreeing_sources_lower_confidence_rather_than_picking_a_winner():
    startup = make_startup()
    evidences = [
        ev(startup, value=1_800_000, source_url="https://press.example/a"),
        ev(startup, value=4_500_000, source_url="https://media.example/b",
           source_type=SourceType.BUSINESS_MEDIA),
    ]
    assessment = assess_field("total_funding_eur", 1_800_000, evidences)
    assert assessment.verification_status == VerificationStatus.UNVERIFIED
    assert assessment.confidence <= 0.4
    assert "disagree" in assessment.note


def test_values_within_ten_percent_count_as_agreement():
    startup = make_startup()
    assert values_agree([ev(startup, value=1_800_000), ev(startup, value=1_850_000)])
    assert not values_agree([ev(startup, value=1_800_000), ev(startup, value=4_000_000)])


def test_the_manager_detects_conflicts():
    startup = make_startup()
    manager = EvidenceManager([
        ev(startup, value=1_800_000, source_url="https://a.example"),
        ev(startup, value=5_000_000, source_url="https://b.example"),
    ])
    assert manager.has_conflict(startup.id, "total_funding_eur") is True
    assert manager.has_conflict(startup.id, "founders") is False


# ----------------------------------------------------------------- manager
def test_refreshing_confidence_syncs_funding_status_onto_the_company():
    startup = make_startup(funding_status=VerificationStatus.MISSING)
    manager = EvidenceManager([ev(startup)])
    manager.refresh_startup_confidence(startup)

    assert startup.funding_status == VerificationStatus.VERIFIED
    assert manager.confidence_of(startup, "total_funding_eur") >= 0.7


def test_one_well_sourced_field_does_not_make_a_whole_company_confident():
    """The headline badge averages the key fields — a single source is not enough."""
    startup = make_startup(funding_status=VerificationStatus.MISSING)
    manager = EvidenceManager([ev(startup)])
    manager.refresh_startup_confidence(startup)
    assert startup.data_confidence == ConfidenceLevel.UNVERIFIED

    for field_name in ("stage", "hq_country", "founded_year", "product_summary", "founders"):
        manager.add(ev(startup, field_name=field_name, value="x",
                       source_url=f"https://press.example/{field_name}"))
    manager.refresh_startup_confidence(startup)
    assert startup.data_confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)


def test_missing_funding_stays_missing_however_much_evidence_exists():
    startup = make_startup(total_funding_eur=None)
    manager = EvidenceManager([ev(startup)])
    manager.refresh_startup_confidence(startup)
    assert startup.funding_status == VerificationStatus.MISSING


def test_source_urls_are_collected_onto_the_company():
    startup = make_startup(source_urls=[])
    manager = EvidenceManager([ev(startup, source_url="https://new.example/story")])
    manager.refresh_startup_confidence(startup)
    assert "https://new.example/story" in startup.source_urls


def test_marking_evidence_verified_is_reversible():
    startup = make_startup()
    manager = EvidenceManager()
    item = manager.add(ev(startup, source_type=SourceType.BLOG))

    manager.mark_verified(item.id, True)
    assert manager.get(item.id).human_verified is True

    manager.mark_verified(item.id, False)
    assert manager.get(item.id).human_verified is False
