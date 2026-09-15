"""The scoring framework — weights, rating guidance, and the rules of the game.

Total is exactly 100 points. The weights live here and nowhere else, so the
framework can be tuned (and a test asserts the total is still 100).

Every criterion is rated 0–5 on evidence, then weighted:

    weighted_score = raw_rating / 5 * weight

A criterion with no evidence gets ``raw_rating = None`` and contributes 0 — but
it is also excluded from ``assessable_weight``, so the UI can say "62 out of a
possible 85 assessed" rather than pretending the missing 15 were a bad score.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    weight: float
    question: str
    rating_guide: dict[int, str]
    evidence_fields: tuple[str, ...]


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        key="thesis_fit",
        label="Thesis Fit",
        weight=20,
        question="How squarely does this company sit inside the fund's stated thesis?",
        rating_guide={
            0: "Outside the thesis on more than one dimension.",
            1: "Adjacent at best; would require stretching the thesis.",
            2: "Matches geography and stage but not the themes.",
            3: "Matches the themes but is marginal on stage or funding.",
            4: "Matches geography, stage, funding and one theme cleanly.",
            5: "Matches every dimension and embodies the thesis characteristics.",
        },
        evidence_fields=("hq_country", "stage", "total_funding_eur", "themes", "sector"),
    ),
    Criterion(
        key="problem_magnitude",
        label="Problem Magnitude / Market Potential",
        weight=20,
        question="How large and how painful is the problem being solved?",
        rating_guide={
            0: "No identifiable problem statement.",
            1: "Niche convenience problem.",
            2: "Real problem, small or unclear market.",
            3: "Meaningful problem with a plausible mid-size market.",
            4: "Severe problem in a large, growing market with a stated size signal.",
            5: "Severe, non-optional problem in a very large market with corroborated sizing.",
        },
        evidence_fields=("market_size_signal", "product_summary", "impact_signal", "customers"),
    ),
    Criterion(
        key="founder_market_fit",
        label="Founder-Market Fit",
        weight=15,
        question="Why is this team uniquely able to solve this particular problem?",
        rating_guide={
            0: "No founder information at all.",
            1: "Founders named, no relevant background evident.",
            2: "General entrepreneurial or technical background, not domain-specific.",
            3: "Relevant adjacent experience.",
            4: "Direct domain experience or strong technical credentials in the field.",
            5: "Rare, hard-to-replicate combination of domain, technical and operating depth.",
        },
        evidence_fields=("founders", "founder_background"),
    ),
    Criterion(
        key="product_differentiation",
        label="Product / Technical Differentiation",
        weight=15,
        question="What stops a well-funded competitor copying this in 12 months?",
        rating_guide={
            0: "No product or technology description.",
            1: "Thin wrapper or undifferentiated offering.",
            2: "Standard technology, differentiation claimed but not substantiated.",
            3: "One concrete defensibility marker.",
            4: "Two independent defensibility markers.",
            5: "Several reinforcing markers (proprietary data, IP, regulatory, lock-in).",
        },
        evidence_fields=("technology", "technical_moat", "product_summary"),
    ),
    Criterion(
        key="traction",
        label="Traction Signals",
        weight=10,
        question="What evidence exists that someone actually wants this?",
        rating_guide={
            0: "No traction evidence of any kind.",
            1: "Pre-launch: waitlist or 'coming soon' only.",
            2: "Unpaid pilots or unnamed usage claims.",
            3: "Named pilots or early paying customers.",
            4: "Multiple named customers or disclosed recurring revenue.",
            5: "Strong commercial traction, corroborated outside the company's own site.",
        },
        evidence_fields=("traction_signals", "customers"),
    ),
    Criterion(
        key="why_now",
        label="Why Now / Market Timing",
        weight=10,
        question="What changed recently that makes this possible or necessary now?",
        rating_guide={
            0: "No timing rationale available.",
            1: "No discernible change; could have been built five years ago.",
            2: "Generic 'AI is improving' style rationale.",
            3: "A plausible technology or cost-curve shift.",
            4: "A concrete regulatory deadline or cost-curve inflection.",
            5: "A hard, dated external forcing function that creates urgent demand.",
        },
        evidence_fields=("why_now_signal", "market_size_signal", "last_round_date"),
    ),
    Criterion(
        key="scalability",
        label="Scalability",
        weight=5,
        question="Can revenue grow far faster than headcount and cost?",
        rating_guide={
            0: "Cannot be assessed.",
            1: "Pure services / day-rate delivery.",
            2: "Heavily bespoke implementations.",
            3: "Mixed product and services model.",
            4: "Product economics with some delivery friction.",
            5: "Clean software / platform economics.",
        },
        evidence_fields=("business_model", "product_summary", "technology"),
    ),
    Criterion(
        key="capital_efficiency",
        label="Capital Efficiency",
        weight=5,
        question="How much has been achieved per euro raised?",
        rating_guide={
            0: "Cannot be assessed (funding unverified).",
            1: "Substantial capital consumed with little evidence of progress.",
            2: "Spend broadly in line with output, nothing notable.",
            3: "Reasonable progress for the amount raised.",
            4: "Clear traction on modest capital.",
            5: "Exceptional output relative to a small raise.",
        },
        evidence_fields=("total_funding_eur", "traction_signals", "founded_year", "customers"),
    ),
)

TOTAL_POINTS: float = sum(c.weight for c in CRITERIA)

CRITERIA_BY_KEY: dict[str, Criterion] = {c.key: c for c in CRITERIA}

#: Thresholds used to turn a total score into a recommendation. Deliberately
#: conservative — the top band is INVESTIGATE, never INVEST.
RECOMMENDATION_THRESHOLDS = {
    "investigate": 68.0,
    "watch": 48.0,
}

#: A run whose evidence coverage is below this cannot reach INVESTIGATE, no
#: matter how high the arithmetic score is.
MIN_COVERAGE_FOR_INVESTIGATE = 0.65
MIN_CONFIDENCE_FOR_INVESTIGATE = 0.45


def validate_weights() -> None:
    """Raise if the framework no longer adds up to 100 points."""
    if round(TOTAL_POINTS, 6) != 100.0:
        raise ValueError(
            f"Scoring weights must total 100, got {TOTAL_POINTS}. Fix src/scoring/score_config.py."
        )


def weights_table() -> list[dict[str, object]]:
    return [
        {"Criterion": c.label, "Weight": c.weight, "What it asks": c.question}
        for c in CRITERIA
    ]


validate_weights()
