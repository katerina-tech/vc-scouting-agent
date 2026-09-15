"""The eligibility engine — deterministic hard filters, run before any scoring.

Non-negotiable rule implemented here: **unknown funding is not eligible funding.**
If the total raised cannot be verified, the company becomes NEEDS_REVIEW with an
explicit reason, never silently ELIGIBLE.

Outcomes:
  ELIGIBLE      — every check passed
  INELIGIBLE    — at least one check failed on evidence
  NEEDS_REVIEW  — nothing failed, but something could not be determined
"""

from __future__ import annotations

from datetime import datetime

from ..models.enums import CheckOutcome, EligibilityStatus, Stage, VerificationStatus
from ..models.scoring import EligibilityCheck, EligibilityResult
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..normalization.company_normalizer import infer_themes, is_european
from ..research.evidence_manager import EvidenceManager


def _geography_check(startup: Startup, thesis: InvestmentThesis, ev_ids: list[str]) -> EligibilityCheck:
    country = startup.hq_country
    if not country:
        return EligibilityCheck(
            check="geography", label="Headquarters in scope", outcome=CheckOutcome.UNKNOWN,
            detail="Headquarters country is unknown.", evidence_ids=ev_ids,
        )
    in_scope = country in thesis.geographies
    if in_scope:
        return EligibilityCheck(
            check="geography", label="Headquarters in scope", outcome=CheckOutcome.PASS,
            detail=f"{country}-based.", evidence_ids=ev_ids,
        )
    # Distinguish "definitely outside Europe" from "unrecognised country string".
    european = is_european(country)
    if european is None:
        return EligibilityCheck(
            check="geography", label="Headquarters in scope", outcome=CheckOutcome.UNKNOWN,
            detail=f"Could not resolve country '{country}'.", evidence_ids=ev_ids,
        )
    return EligibilityCheck(
        check="geography", label="Headquarters in scope", outcome=CheckOutcome.FAIL,
        detail=f"{country} is outside {thesis.geography_label}.", evidence_ids=ev_ids,
    )


def _active_check(startup: Startup, thesis: InvestmentThesis, ev_ids: list[str]) -> EligibilityCheck:
    if not thesis.require_active:
        return EligibilityCheck(
            check="active", label="Company is active", outcome=CheckOutcome.PASS,
            detail="Active status not required by this thesis.",
        )
    if startup.is_active is None:
        return EligibilityCheck(
            check="active", label="Company is active", outcome=CheckOutcome.UNKNOWN,
            detail="Operating status could not be confirmed.", evidence_ids=ev_ids,
        )
    if startup.is_active:
        return EligibilityCheck(
            check="active", label="Company is active", outcome=CheckOutcome.PASS,
            detail="Company appears to be operating.", evidence_ids=ev_ids,
        )
    return EligibilityCheck(
        check="active", label="Company is active", outcome=CheckOutcome.FAIL,
        detail="Company appears inactive, closed or acquired.", evidence_ids=ev_ids,
    )


def _stage_check(startup: Startup, thesis: InvestmentThesis, ev_ids: list[str]) -> EligibilityCheck:
    if startup.stage == Stage.UNKNOWN:
        return EligibilityCheck(
            check="stage", label="Stage within thesis", outcome=CheckOutcome.UNKNOWN,
            detail="Funding stage is unknown.", evidence_ids=ev_ids,
        )
    wanted = ", ".join(sorted(s.label for s in thesis.stages))
    if startup.stage in thesis.stages:
        return EligibilityCheck(
            check="stage", label="Stage within thesis", outcome=CheckOutcome.PASS,
            detail=f"{startup.stage.label} stage.", evidence_ids=ev_ids,
        )
    return EligibilityCheck(
        check="stage", label="Stage within thesis", outcome=CheckOutcome.FAIL,
        detail=f"{startup.stage.label} is outside the thesis ({wanted}).", evidence_ids=ev_ids,
    )


def _funding_check(startup: Startup, thesis: InvestmentThesis, ev_ids: list[str]) -> EligibilityCheck:
    ceiling = thesis.max_total_funding_eur
    amount = startup.total_funding_eur

    if amount is None:
        return EligibilityCheck(
            check="funding", label=f"Total funding below €{ceiling:,.0f}",
            outcome=CheckOutcome.UNKNOWN,
            detail="Funding amount could not be verified — NOT assumed to be below the ceiling.",
            evidence_ids=ev_ids,
        )

    if amount >= ceiling:
        return EligibilityCheck(
            check="funding", label=f"Total funding below €{ceiling:,.0f}",
            outcome=CheckOutcome.FAIL,
            detail=f"€{amount:,.0f} raised — at or above the €{ceiling:,.0f} ceiling.",
            evidence_ids=ev_ids,
        )

    if startup.funding_status != VerificationStatus.VERIFIED:
        return EligibilityCheck(
            check="funding", label=f"Total funding below €{ceiling:,.0f}",
            outcome=CheckOutcome.UNKNOWN,
            detail=(
                f"€{amount:,.0f} reported but {startup.funding_status.value} — "
                "needs a credible source before it counts."
            ),
            evidence_ids=ev_ids,
        )

    return EligibilityCheck(
        check="funding", label=f"Total funding below €{ceiling:,.0f}",
        outcome=CheckOutcome.PASS,
        detail=f"€{amount:,.0f} verified total funding.", evidence_ids=ev_ids,
    )


def _theme_check(startup: Startup, thesis: InvestmentThesis, ev_ids: list[str]) -> EligibilityCheck:
    themes = startup.themes or infer_themes(
        startup.sector, startup.subsector, startup.product_summary, startup.impact_signal
    )
    if not themes:
        return EligibilityCheck(
            check="theme", label="Matches a thesis theme", outcome=CheckOutcome.UNKNOWN,
            detail="Could not map this company to any thesis theme from available text.",
            evidence_ids=ev_ids,
        )
    wanted = {t.strip().lower() for t in thesis.themes}
    matched = [t for t in themes if t.strip().lower() in wanted]
    if matched:
        return EligibilityCheck(
            check="theme", label="Matches a thesis theme", outcome=CheckOutcome.PASS,
            detail=f"Matches: {', '.join(matched)}.", evidence_ids=ev_ids,
        )
    return EligibilityCheck(
        check="theme", label="Matches a thesis theme", outcome=CheckOutcome.FAIL,
        detail=f"Themes found ({', '.join(themes)}) do not match the thesis.",
        evidence_ids=ev_ids,
    )


def _founded_check(startup: Startup, thesis: InvestmentThesis, ev_ids: list[str]) -> EligibilityCheck:
    floor = thesis.min_founded_year
    if floor is None:
        return EligibilityCheck(
            check="founded_year", label="Founding year in scope", outcome=CheckOutcome.PASS,
            detail="No founding-year constraint in this thesis.",
        )
    if startup.founded_year is None:
        return EligibilityCheck(
            check="founded_year", label=f"Founded {floor} or later",
            outcome=CheckOutcome.UNKNOWN, detail="Founding year is unknown.",
            evidence_ids=ev_ids,
        )
    if startup.founded_year >= floor:
        return EligibilityCheck(
            check="founded_year", label=f"Founded {floor} or later", outcome=CheckOutcome.PASS,
            detail=f"Founded {startup.founded_year}.", evidence_ids=ev_ids,
        )
    return EligibilityCheck(
        check="founded_year", label=f"Founded {floor} or later", outcome=CheckOutcome.FAIL,
        detail=f"Founded {startup.founded_year}, before the {floor} cut-off.",
        evidence_ids=ev_ids,
    )


def evaluate_eligibility(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
) -> EligibilityResult:
    """Run every hard filter and explain each decision."""
    em = evidence

    def ids(*fields: str) -> list[str]:
        return em.evidence_ids_for(startup, *fields) if em else []

    checks = [
        _geography_check(startup, thesis, ids("hq_country")),
        _active_check(startup, thesis, ids("is_active", "website")),
        _stage_check(startup, thesis, ids("stage")),
        _funding_check(startup, thesis, ids("total_funding_eur")),
        _theme_check(startup, thesis, ids("sector", "themes", "product_summary")),
        _founded_check(startup, thesis, ids("founded_year")),
    ]

    failed = [c for c in checks if c.outcome == CheckOutcome.FAIL]
    unknown = [c for c in checks if c.outcome == CheckOutcome.UNKNOWN]

    if failed:
        status = EligibilityStatus.INELIGIBLE
        reasons = [f"Ineligible: {c.detail or c.label}" for c in failed]
        reasons += [f"Also unresolved: {c.detail or c.label}" for c in unknown]
    elif unknown:
        status = EligibilityStatus.NEEDS_REVIEW
        reasons = [f"Needs review: {c.detail or c.label}" for c in unknown]
        reasons += [f"Passed: {c.detail or c.label}" for c in checks if c.outcome == CheckOutcome.PASS]
    else:
        status = EligibilityStatus.ELIGIBLE
        reasons = [f"Eligible: {c.detail or c.label}" for c in checks]

    return EligibilityResult(status=status, checks=checks, reasons=reasons)


def apply_eligibility(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
) -> Startup:
    """Evaluate and write the result back onto the startup."""
    result = evaluate_eligibility(startup, thesis, evidence)
    startup.eligibility_result = result
    startup.eligibility_status = result.status
    startup.eligibility_reasons = result.reasons
    startup.touch()
    return startup


def eligibility_summary(startups: list[Startup]) -> dict[str, int]:
    counts = {s.value: 0 for s in EligibilityStatus}
    for s in startups:
        counts[s.eligibility_status.value] += 1
    return counts


def current_year() -> int:
    return datetime.now().year
