"""Scoring: weights, arithmetic, and the missing-evidence rule."""

from __future__ import annotations

import pytest

from src.models.enums import Stage, VerificationStatus
from src.models.scoring import CriterionScore, ScoreBreakdown
from src.scoring.score_config import CRITERIA, TOTAL_POINTS, validate_weights
from src.scoring.score_engine import (
    merge_llm_ratings,
    override_criterion,
    rank,
    score_startup,
    apply_score,
)
from tests.conftest import make_startup


# ----------------------------------------------------------------- framework
def test_weights_sum_to_exactly_100():
    assert TOTAL_POINTS == 100.0
    validate_weights()


def test_the_framework_has_the_eight_specified_criteria():
    expected = {
        "thesis_fit": 20, "problem_magnitude": 20, "founder_market_fit": 15,
        "product_differentiation": 15, "traction": 10, "why_now": 10,
        "scalability": 5, "capital_efficiency": 5,
    }
    assert {c.key: c.weight for c in CRITERIA} == expected


def test_every_criterion_has_a_full_rating_guide():
    for criterion in CRITERIA:
        assert set(criterion.rating_guide) == {0, 1, 2, 3, 4, 5}
        assert criterion.evidence_fields


# ---------------------------------------------------------------- arithmetic
@pytest.mark.parametrize(
    "rating, weight, expected",
    [(5, 20, 20.0), (4, 15, 12.0), (3, 10, 6.0), (0, 20, 0.0), (2, 5, 2.0)],
)
def test_weighted_score_is_rating_over_five_times_weight(rating, weight, expected):
    criterion = CriterionScore(criterion="x", label="X", raw_rating=rating, weight=weight)
    assert criterion.weighted_score == expected


def test_a_perfect_company_cannot_exceed_100():
    breakdown = ScoreBreakdown(criteria=[
        CriterionScore(criterion=c.key, label=c.label, raw_rating=5, weight=c.weight,
                       confidence=1.0)
        for c in CRITERIA
    ])
    assert breakdown.score_total == 100.0
    assert breakdown.evidence_coverage == 1.0


# ---------------------------------------------------------- missing evidence
def test_a_criterion_with_no_evidence_is_unrated_not_zero_rated(thesis):
    startup = make_startup(traction_signals=[], customers=[])
    breakdown = score_startup(startup, thesis)
    traction = breakdown.get("traction")

    assert traction.raw_rating is None, "no evidence must mean no rating, not a rating of 0"
    assert traction.evidence_missing is True
    assert traction.weighted_score == 0.0
    assert "Not scored" in traction.reasoning


def test_unscored_weight_is_excluded_from_the_assessable_total(thesis):
    startup = make_startup(traction_signals=[], customers=[])
    breakdown = score_startup(startup, thesis)
    assert breakdown.assessable_weight == 90.0  # traction is worth 10
    assert breakdown.evidence_coverage == 0.9


def test_a_company_with_no_data_at_all_scores_nothing_and_says_so(thesis):
    empty = make_startup(
        hq_country=None, stage=Stage.UNKNOWN, total_funding_eur=None,
        funding_status=VerificationStatus.MISSING, themes=[], sector=None, subsector=None,
        founders=[], founder_background=None, product_summary=None, business_model=None,
        customers=[], traction_signals=[], technology=None, technical_moat=None,
        market_size_signal=None, impact_signal=None, why_now_signal=None,
    )
    breakdown = score_startup(empty, thesis)
    assert breakdown.score_total == 0.0
    assert breakdown.assessable_weight == 0.0
    assert len(breakdown.unscored_criteria) == len(CRITERIA)
    assert breakdown.notes


def test_capital_efficiency_refuses_to_score_unverified_funding(thesis):
    startup = make_startup(funding_status=VerificationStatus.UNVERIFIED)
    criterion = score_startup(startup, thesis).get("capital_efficiency")
    assert criterion.raw_rating is None
    assert "not scored on unverified numbers" in criterion.reasoning


def test_unquantified_market_claims_do_not_earn_market_points(thesis):
    vague = score_startup(make_startup(market_size_signal="a large market"), thesis)
    quantified = score_startup(make_startup(market_size_signal="€12bn market"), thesis)
    assert vague.score_for("problem_magnitude") < quantified.score_for("problem_magnitude")


# -------------------------------------------------------------- thesis fit
def test_thesis_fit_rewards_a_full_match(thesis):
    assert score_startup(make_startup(), thesis).get("thesis_fit").raw_rating >= 4


def test_thesis_fit_punishes_an_out_of_scope_company(thesis):
    off = make_startup(hq_country="United States", stage=Stage.SERIES_A,
                       total_funding_eur=20_000_000.0, themes=["Other"])
    assert score_startup(off, thesis).get("thesis_fit").raw_rating <= 1


# ------------------------------------------------------------- LLM merging
def test_the_llm_cannot_invent_a_score_where_no_evidence_exists(thesis):
    startup = make_startup(traction_signals=[], customers=[])
    breakdown = score_startup(startup, thesis)
    before = breakdown.score_total

    merge_llm_ratings(breakdown, {"traction": {"rating": 5, "confidence": 0.9,
                                               "reasoning": "They feel traction-y."}})

    assert breakdown.get("traction").raw_rating is None
    assert breakdown.score_total == before
    assert "rejected" in breakdown.get("traction").reasoning


def test_the_llm_may_adjust_a_criterion_that_does_have_evidence(thesis):
    breakdown = score_startup(make_startup(), thesis)
    merge_llm_ratings(breakdown, {"traction": {"rating": 2, "confidence": 0.5,
                                               "reasoning": "Only two customers."}})
    traction = breakdown.get("traction")
    assert traction.raw_rating == 2
    assert traction.source == "llm"
    assert "Only two customers." in traction.reasoning


def test_invented_criteria_from_the_llm_are_ignored(thesis):
    breakdown = score_startup(make_startup(), thesis)
    before = breakdown.score_total
    merge_llm_ratings(breakdown, {"vibes": {"rating": 5, "confidence": 1.0}})
    assert breakdown.score_total == before
    assert breakdown.get("vibes") is None


# --------------------------------------------------------------- overrides
def test_a_human_override_is_applied_and_recorded(thesis):
    startup = apply_score(make_startup(), thesis)
    override_criterion(startup, "traction", 5, "I spoke to two of their customers.")
    traction = startup.score_breakdown.get("traction")

    assert traction.raw_rating == 5
    assert traction.source == "human_override"
    assert startup.human_overrides[-1].field_name == "score.traction"
    assert startup.score_total == startup.score_breakdown.score_total


def test_an_override_can_rescue_a_criterion_that_had_no_evidence(thesis):
    startup = apply_score(make_startup(traction_signals=[], customers=[]), thesis)
    assert startup.score_breakdown.get("traction").raw_rating is None
    override_criterion(startup, "traction", 4, "Saw the signed contracts in the data room.")
    assert startup.score_breakdown.get("traction").raw_rating == 4
    assert startup.score_breakdown.get("traction").evidence_missing is False


# ----------------------------------------------------------------- ranking
def test_ranking_excludes_companies_that_are_not_rankable(thesis):
    from src.filters.eligibility import apply_eligibility

    good = apply_score(apply_eligibility(make_startup(), thesis), thesis)
    bad = apply_score(apply_eligibility(make_startup(hq_country="United States"), thesis), thesis)

    ranked = rank([good, bad])
    assert good in ranked
    assert bad not in ranked


def test_ties_break_towards_better_evidenced_companies():
    from src.models.enums import EligibilityStatus

    def build(coverage_full: bool, name: str):
        startup = make_startup(company_name=name)
        startup.eligibility_status = EligibilityStatus.ELIGIBLE
        criteria = [
            CriterionScore(criterion=c.key, label=c.label,
                           raw_rating=3 if (coverage_full or c.weight >= 15) else None,
                           weight=c.weight, confidence=0.8)
            for c in CRITERIA
        ]
        startup.score_breakdown = ScoreBreakdown(criteria=criteria)
        startup.score_total = 60.0  # forced tie
        return startup

    thin = build(False, "Thin GmbH")
    thorough = build(True, "Thorough GmbH")
    assert rank([thin, thorough])[0].company_name == "Thorough GmbH"
