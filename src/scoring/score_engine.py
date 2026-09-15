"""The scoring engine.

Everything here is deterministic and inspectable. An LLM may *propose* a rating
(see ``llm/investment_analyst.py``), but it is merged in only where the
deterministic engine found evidence, it is labelled ``source="llm"``, and it can
always be overridden by the investor.

The single most important rule in this file:

    if there is no evidence for a criterion, the rating is None.

Not 0, not the average, not "3 because most things are 3". None — and the UI
says so.
"""

from __future__ import annotations

import re
from datetime import date

from ..enrichment.founders import founder_market_fit_signals
from ..enrichment.technology import moat_strength, scalability_signal
from ..models.enums import Stage, VerificationStatus
from ..models.scoring import CriterionScore, ScoreBreakdown
from ..models.startup import HumanOverride, Startup
from ..models.thesis import InvestmentThesis
from ..research.evidence_manager import EvidenceManager
from .score_config import CRITERIA, CRITERIA_BY_KEY, Criterion, validate_weights

ENGINE_VERSION = "1.0"


def _ids(evidence: EvidenceManager | None, startup: Startup, criterion: Criterion) -> list[str]:
    if evidence is None:
        return []
    return evidence.evidence_ids_for(startup, *criterion.evidence_fields)


def _confidence(evidence: EvidenceManager | None, startup: Startup, criterion: Criterion) -> float:
    """Average confidence of the fields this criterion actually depends on."""
    if evidence is None:
        return 0.2
    scores = [evidence.confidence_of(startup, f) for f in criterion.evidence_fields]
    scores = [s for s in scores if s > 0]
    if not scores:
        return 0.1
    return round(sum(scores) / len(scores), 3)


def _missing(criterion: Criterion, reason: str) -> CriterionScore:
    return CriterionScore(
        criterion=criterion.key,
        label=criterion.label,
        raw_rating=None,
        weight=criterion.weight,
        reasoning=f"Not scored — {reason}",
        confidence=0.0,
        evidence_missing=True,
    )


# --------------------------------------------------------------------------- #
# Individual criterion raters
# --------------------------------------------------------------------------- #

def _rate_thesis_fit(startup: Startup, thesis: InvestmentThesis) -> tuple[int | None, str]:
    dimensions: list[tuple[str, bool | None]] = [
        ("geography", thesis.matches_geography(startup.hq_country)),
        ("stage", thesis.matches_stage(startup.stage)),
        ("theme", thesis.matches_theme(startup.themes)),
    ]
    if startup.total_funding_eur is None:
        dimensions.append(("funding ceiling", None))
    else:
        dimensions.append(("funding ceiling", startup.total_funding_eur < thesis.max_total_funding_eur))

    known = [(name, ok) for name, ok in dimensions if ok is not None]
    if not known:
        return None, "nothing about this company could be compared against the thesis."

    matched = [name for name, ok in known if ok]
    missed = [name for name, ok in known if not ok]
    unknown = [name for name, ok in dimensions if ok is None]

    ratio = len(matched) / len(dimensions)
    rating = max(0, min(5, round(ratio * 5)))

    # A characteristic bonus, but only when the text actually supports it.
    text = " ".join(p for p in [startup.product_summary, startup.business_model,
                                startup.technology, startup.impact_signal] if p).lower()
    hits = [c for c in thesis.characteristics if any(w in text for w in c.split() if len(w) > 4)]
    if hits and rating < 5 and not missed:
        rating = min(5, rating + 1)

    parts = [f"matches {', '.join(matched)}" if matched else "matches nothing in the thesis"]
    if missed:
        parts.append(f"does not match {', '.join(missed)}")
    if unknown:
        parts.append(f"unknown: {', '.join(unknown)}")
    if hits:
        parts.append(f"thesis characteristics echoed in the text: {', '.join(hits)}")
    return rating, "; ".join(parts) + "."


def _rate_problem_magnitude(startup: Startup) -> tuple[int | None, str]:
    has_problem_text = bool(startup.product_summary)
    size = startup.market_size_signal
    impact = startup.impact_signal
    if not has_problem_text and not size:
        return None, "no problem statement or market signal is available."

    rating = 2
    reasons = []
    if size and re.search(r"\d", size):
        rating += 2
        reasons.append(f"quantified market-size signal present ({size[:90]})")
    elif size:
        reasons.append(
            f"a market-size claim exists but carries no figure (“{size[:70]}”), so it does "
            "not substantiate the opportunity"
        )
    else:
        reasons.append("no market-size signal recorded")
    if impact:
        rating += 1
        reasons.append("a measurable impact dimension is described")
    if startup.customers:
        reasons.append(f"{len(startup.customers)} named customer(s) suggest a real buyer exists")
        rating = min(5, rating + 1)
    if not has_problem_text:
        rating -= 1
        reasons.append("the problem itself is not described in the record")

    return max(0, min(5, rating)), "; ".join(reasons) + "."


def _rate_founder_market_fit(startup: Startup) -> tuple[int | None, str]:
    if not startup.founders and not startup.founder_background:
        return None, "no founder names or background are available."
    if not startup.founder_background:
        return 1, (
            f"{len(startup.founders)} founder(s) named but no background information — "
            "founder-market fit cannot be assessed beyond their existence."
        )

    overlap = founder_market_fit_signals(startup)
    background = startup.founder_background.lower()
    depth_markers = [
        kw for kw in ("phd", "professor", "md ", "clinician", "years", "ex-", "previously",
                      "founded", "led", "head of", "director", "engineer", "researcher")
        if kw in background
    ]

    rating = 2
    reasons = [f"background recorded ({len(startup.founder_background)} chars)"]
    if overlap:
        rating += 1
        reasons.append(f"domain-word overlap with the company's own field: {', '.join(overlap[:5])}")
    if len(depth_markers) >= 3:
        rating += 2
        reasons.append(f"seniority/credential markers: {', '.join(depth_markers[:4])}")
    elif depth_markers:
        rating += 1
        reasons.append(f"some seniority markers: {', '.join(depth_markers)}")
    if not overlap:
        reasons.append("⚠️ no obvious overlap between founder background and the company's domain")

    return max(0, min(5, rating)), "; ".join(reasons) + "."


def _rate_product_differentiation(startup: Startup) -> tuple[int | None, str]:
    return moat_strength(startup)


def _rate_traction(startup: Startup) -> tuple[int | None, str]:
    if not startup.traction_signals and not startup.customers:
        return None, "no traction evidence of any kind was found."

    blob = " ".join(startup.traction_signals).lower()
    named = len(startup.customers)
    rating = 1
    reasons = []

    if named >= 3:
        rating = 4
        reasons.append(f"{named} named customers")
    elif named >= 1:
        rating = 3
        reasons.append(f"{named} named customer(s)")

    if any(k in blob for k in ("revenue", "arr", "mrr", "paying")):
        rating = max(rating, 4)
        reasons.append("recurring or paying revenue referenced")
    if any(k in blob for k in ("contract", "letter of intent", "loi", "tender")):
        rating = max(rating, 4)
        reasons.append("contract or LOI language")
    if any(k in blob for k in ("pilot", "proof of concept", "poc")):
        rating = max(rating, 3)
        reasons.append("pilots under way")
    if any(k in blob for k in ("waitlist", "coming soon", "early access", "aspirational")):
        rating = min(rating, 2)
        reasons.append("⚠️ pre-launch language suggests traction may be aspirational")
    if not reasons:
        rating = 2
        reasons.append("traction claims present but unspecific")

    reasons.append("all traction is self-reported unless a third-party source was attached")
    return max(0, min(5, rating)), "; ".join(reasons) + "."


def _rate_why_now(startup: Startup) -> tuple[int | None, str]:
    signal = startup.why_now_signal
    if not signal:
        return None, "no timing rationale is available in the record."

    lowered = signal.lower()
    rating = 2
    reasons = [f"timing signal recorded: {signal[:110]}"]
    if "regulatory driver" in lowered or any(
        r in lowered for r in ("csrd", "cbam", "ai act", "mdr", "nis2", "eudr", "taxonomy")
    ):
        rating = 4
        reasons.append("a named regulation is the forcing function")
    if any(r in lowered for r in ("deadline", "comes into force", "mandatory from", "from 202")):
        rating = 5
        reasons.append("a dated deadline creates urgency")
    elif "cost" in lowered and any(w in lowered for w in ("fallen", "dropped", "collapsed")):
        rating = max(rating, 4)
        reasons.append("a cost-curve inflection is cited")

    return max(0, min(5, rating)), "; ".join(reasons) + "."


def _rate_scalability(startup: Startup) -> tuple[int | None, str]:
    return scalability_signal(startup)


def _rate_capital_efficiency(startup: Startup) -> tuple[int | None, str]:
    if startup.total_funding_eur is None:
        return None, "total funding is unknown, so capital efficiency cannot be computed."
    if startup.funding_status != VerificationStatus.VERIFIED:
        return None, (
            f"the funding figure is {startup.funding_status.value} — capital efficiency is "
            "not scored on unverified numbers."
        )

    funding = startup.total_funding_eur
    years = None
    if startup.founded_year:
        years = max(1, date.today().year - startup.founded_year)

    traction_weight = len(startup.customers) + len(startup.traction_signals)
    burn_per_year = funding / years if years else funding

    reasons = [f"€{funding:,.0f} raised"]
    if years:
        reasons.append(f"over ~{years} year(s) (≈€{burn_per_year:,.0f}/year)")

    if traction_weight == 0:
        rating = 2 if funding < 500_000 else 1
        reasons.append("no traction recorded against that capital")
    elif funding < 1_000_000 and traction_weight >= 3:
        rating = 5
        reasons.append("meaningful traction on under €1M")
    elif funding < 2_000_000 and traction_weight >= 2:
        rating = 4
        reasons.append("reasonable traction relative to capital raised")
    elif traction_weight >= 2:
        rating = 3
        reasons.append("traction broadly in line with capital raised")
    else:
        rating = 2
        reasons.append("limited evidence of output for the capital raised")

    return rating, "; ".join(reasons) + "."


_RATERS = {
    "thesis_fit": None,  # needs the thesis, handled specially
    "problem_magnitude": _rate_problem_magnitude,
    "founder_market_fit": _rate_founder_market_fit,
    "product_differentiation": _rate_product_differentiation,
    "traction": _rate_traction,
    "why_now": _rate_why_now,
    "scalability": _rate_scalability,
    "capital_efficiency": _rate_capital_efficiency,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def score_startup(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
) -> ScoreBreakdown:
    """Produce the full, explained 100-point breakdown for one company."""
    validate_weights()
    criteria_scores: list[CriterionScore] = []

    for criterion in CRITERIA:
        if criterion.key == "thesis_fit":
            rating, reasoning = _rate_thesis_fit(startup, thesis)
        else:
            rater = _RATERS[criterion.key]
            rating, reasoning = rater(startup)  # type: ignore[misc]

        if rating is None:
            criteria_scores.append(_missing(criterion, reasoning))
            continue

        criteria_scores.append(
            CriterionScore(
                criterion=criterion.key,
                label=criterion.label,
                raw_rating=int(rating),
                weight=criterion.weight,
                reasoning=reasoning,
                evidence_ids=_ids(evidence, startup, criterion),
                confidence=_confidence(evidence, startup, criterion),
                source="deterministic",
            )
        )

    breakdown = ScoreBreakdown(criteria=criteria_scores, engine_version=ENGINE_VERSION)
    unscored = breakdown.unscored_criteria
    if unscored:
        breakdown.notes.append(
            f"{len(unscored)} of {len(CRITERIA)} criteria could not be scored for lack of "
            f"evidence ({', '.join(c.label for c in unscored)}). "
            f"Only {breakdown.assessable_weight:.0f} of 100 points were assessable."
        )
    return breakdown


def apply_score(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
) -> Startup:
    breakdown = score_startup(startup, thesis, evidence)
    startup.score_breakdown = breakdown
    startup.score_total = breakdown.score_total
    startup.touch()
    return startup


def merge_llm_ratings(
    breakdown: ScoreBreakdown,
    llm_ratings: dict[str, dict],
    *,
    only_where_deterministic_scored: bool = True,
) -> ScoreBreakdown:
    """Blend LLM-proposed ratings into an existing breakdown.

    The LLM never *creates* a score where the deterministic engine found no
    evidence — that would be exactly the fabrication this product forbids. It
    can only adjust a rating that already rests on evidence, and its reasoning
    is stored alongside, marked ``source="llm"``.
    """
    for criterion_score in breakdown.criteria:
        proposal = llm_ratings.get(criterion_score.criterion)
        if not proposal:
            continue
        if only_where_deterministic_scored and not criterion_score.is_scored:
            criterion_score.reasoning += (
                " (The analyst model also declined to rate this without evidence.)"
                if proposal.get("rating") is None
                else " (An LLM proposed a rating here, but it was rejected: no evidence exists.)"
            )
            continue
        rating = proposal.get("rating")
        if rating is None:
            continue
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            continue
        if not 0 <= rating <= 5:
            continue
        criterion_score.raw_rating = rating
        criterion_score.source = "llm"
        criterion_score.confidence = min(
            criterion_score.confidence,
            float(proposal.get("confidence", criterion_score.confidence) or 0.0),
        )
        llm_reason = str(proposal.get("reasoning", "")).strip()
        if llm_reason:
            criterion_score.reasoning = (
                f"{llm_reason} · [deterministic view: {criterion_score.reasoning}]"
            )
    return breakdown


def override_criterion(
    startup: Startup, criterion_key: str, rating: int, reason: str, author: str = "investor"
) -> Startup:
    """Investor override of a single criterion, recorded permanently."""
    if startup.score_breakdown is None:
        return startup
    criterion_score = startup.score_breakdown.get(criterion_key)
    if criterion_score is None:
        return startup

    old = criterion_score.raw_rating
    criterion_score.raw_rating = max(0, min(5, int(rating)))
    criterion_score.source = "human_override"
    criterion_score.evidence_missing = False
    criterion_score.confidence = max(criterion_score.confidence, 0.9)
    criterion_score.reasoning = (
        f"[Investor override] {reason.strip() or 'No reason given.'} "
        f"· previous: {old if old is not None else 'not scored'}"
    )
    startup.score_total = startup.score_breakdown.score_total
    startup.human_overrides.append(
        HumanOverride(
            field_name=f"score.{criterion_key}", old_value=old, new_value=rating,
            reason=reason, author=author,
        )
    )
    startup.touch()
    return startup


def rank(startups: list[Startup]) -> list[Startup]:
    """Rank only companies that are eligible or human-approved.

    Ties break towards higher evidence coverage, then fewer red flags — a
    well-evidenced 70 should outrank a speculative 70.
    """
    rankable = [s for s in startups if s.is_rankable and s.score_total is not None]
    return sorted(
        rankable,
        key=lambda s: (
            s.score_total or 0.0,
            s.score_breakdown.evidence_coverage if s.score_breakdown else 0.0,
            -s.red_flag_count,
        ),
        reverse=True,
    )


def criterion_label(key: str) -> str:
    criterion = CRITERIA_BY_KEY.get(key)
    return criterion.label if criterion else key
