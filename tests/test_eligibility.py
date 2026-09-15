"""Eligibility: the hard filters, and above all the unknown-funding rule."""

from __future__ import annotations

from src.models.enums import CheckOutcome, EligibilityStatus, Stage, VerificationStatus
from src.filters.eligibility import evaluate_eligibility
from tests.conftest import make_startup


def _check(result, name):
    return next(c for c in result.checks if c.check == name)


# --------------------------------------------------------------- happy path
def test_a_fully_evidenced_in_thesis_company_is_eligible(thesis):
    result = evaluate_eligibility(make_startup(), thesis)
    assert result.status == EligibilityStatus.ELIGIBLE
    assert all(c.outcome == CheckOutcome.PASS for c in result.checks)
    assert any("Germany" in reason for reason in result.reasons)


# ------------------------------------------------------------------ funding
def test_funding_below_ceiling_passes_when_verified(thesis):
    startup = make_startup(total_funding_eur=2_900_000.0)
    assert _check(evaluate_eligibility(startup, thesis), "funding").outcome == CheckOutcome.PASS


def test_funding_at_the_ceiling_fails(thesis):
    startup = make_startup(total_funding_eur=3_000_000.0)
    result = evaluate_eligibility(startup, thesis)
    assert _check(result, "funding").outcome == CheckOutcome.FAIL
    assert result.status == EligibilityStatus.INELIGIBLE


def test_funding_above_ceiling_fails(thesis):
    startup = make_startup(total_funding_eur=12_000_000.0)
    assert evaluate_eligibility(startup, thesis).status == EligibilityStatus.INELIGIBLE


def test_unknown_funding_is_never_assumed_to_be_under_the_ceiling(thesis):
    """The single most important rule in the product."""
    startup = make_startup(
        total_funding_eur=None, funding_status=VerificationStatus.MISSING
    )
    result = evaluate_eligibility(startup, thesis)

    assert result.status == EligibilityStatus.NEEDS_REVIEW
    assert result.status != EligibilityStatus.ELIGIBLE
    funding_check = _check(result, "funding")
    assert funding_check.outcome == CheckOutcome.UNKNOWN
    assert "NOT assumed" in funding_check.detail


def test_reported_but_unverified_funding_needs_review(thesis):
    """A number with no credible source does not make a company eligible."""
    startup = make_startup(
        total_funding_eur=1_200_000.0, funding_status=VerificationStatus.UNVERIFIED
    )
    result = evaluate_eligibility(startup, thesis)
    assert result.status == EligibilityStatus.NEEDS_REVIEW
    assert _check(result, "funding").outcome == CheckOutcome.UNKNOWN


def test_funding_above_ceiling_fails_even_when_unverified(thesis):
    """Too much money is disqualifying regardless of how well sourced it is."""
    startup = make_startup(
        total_funding_eur=9_000_000.0, funding_status=VerificationStatus.UNVERIFIED
    )
    assert _check(evaluate_eligibility(startup, thesis), "funding").outcome == CheckOutcome.FAIL


# ---------------------------------------------------------------- geography
def test_non_european_company_is_ineligible(thesis):
    startup = make_startup(hq_country="United States")
    result = evaluate_eligibility(startup, thesis)
    assert result.status == EligibilityStatus.INELIGIBLE
    assert _check(result, "geography").outcome == CheckOutcome.FAIL


def test_unknown_country_needs_review_rather_than_rejection(thesis):
    startup = make_startup(hq_country=None)
    result = evaluate_eligibility(startup, thesis)
    assert result.status == EligibilityStatus.NEEDS_REVIEW
    assert _check(result, "geography").outcome == CheckOutcome.UNKNOWN


# -------------------------------------------------------------------- stage
def test_series_a_is_outside_the_thesis(thesis):
    result = evaluate_eligibility(make_startup(stage=Stage.SERIES_A), thesis)
    assert _check(result, "stage").outcome == CheckOutcome.FAIL


def test_unknown_stage_needs_review(thesis):
    result = evaluate_eligibility(make_startup(stage=Stage.UNKNOWN), thesis)
    assert _check(result, "stage").outcome == CheckOutcome.UNKNOWN
    assert result.status == EligibilityStatus.NEEDS_REVIEW


# ------------------------------------------------------------------- themes
def test_off_theme_company_is_ineligible(thesis):
    startup = make_startup(sector="Gaming", themes=["Other"], product_summary="A mobile game")
    result = evaluate_eligibility(startup, thesis)
    assert _check(result, "theme").outcome == CheckOutcome.FAIL


def test_untypeable_company_needs_review(thesis):
    startup = make_startup(
        sector=None, subsector=None, themes=[], product_summary=None, impact_signal=None
    )
    assert _check(evaluate_eligibility(startup, thesis), "theme").outcome == CheckOutcome.UNKNOWN


# ------------------------------------------------------------------- active
def test_inactive_company_is_ineligible(thesis):
    result = evaluate_eligibility(make_startup(is_active=False), thesis)
    assert result.status == EligibilityStatus.INELIGIBLE


def test_unknown_activity_needs_review(thesis):
    result = evaluate_eligibility(make_startup(is_active=None), thesis)
    assert _check(result, "active").outcome == CheckOutcome.UNKNOWN


# -------------------------------------------------------------- founded year
def test_company_founded_before_the_floor_fails(thesis):
    result = evaluate_eligibility(make_startup(founded_year=2010), thesis)
    assert _check(result, "founded_year").outcome == CheckOutcome.FAIL


def test_a_failure_outranks_an_unknown(thesis):
    """One hard failure makes a company ineligible even with other gaps."""
    startup = make_startup(hq_country="United States", stage=Stage.UNKNOWN)
    result = evaluate_eligibility(startup, thesis)
    assert result.status == EligibilityStatus.INELIGIBLE


# ------------------------------------------------------------------ reasons
def test_every_decision_carries_reasons(thesis):
    for startup in (
        make_startup(),
        make_startup(total_funding_eur=None, funding_status=VerificationStatus.MISSING),
        make_startup(hq_country="United States"),
    ):
        result = evaluate_eligibility(startup, thesis)
        assert result.reasons, "an eligibility decision must always explain itself"
        assert len(result.checks) == 6
