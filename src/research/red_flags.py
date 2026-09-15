"""Red-flag detection.

Red flags are shown *beside* the score, never subtracted from it. A crowded
market is a reason to ask a question, not a reason for the tool to silently
demote a company. The investor decides.

Every flag names the specific thing that triggered it, so it can be dismissed
if the investor knows better.
"""

from __future__ import annotations

import re
from datetime import date

from ..models.enums import RedFlagSeverity, Stage, VerificationStatus
from ..models.scoring import RedFlag
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from .evidence_manager import EvidenceManager

_CONSULTING_RE = re.compile(
    r"\b(consult(?:ing|ancy)|agency|bespoke (?:projects|engagements)|day rate|"
    r"professional services|systems integration)\b", re.IGNORECASE,
)
_SAAS_RE = re.compile(r"\b(saas|subscription|platform|per-seat|licen[cs]e fee|arr|mrr)\b", re.IGNORECASE)
_CROWDED_RE = re.compile(
    r"\b(crowded|commoditi[sz]ed|dozens of (?:players|competitors|startups)|"
    r"highly competitive|many alternatives)\b", re.IGNORECASE,
)
_ACQUIRED_RE = re.compile(r"\b(acquired by|has been acquired|merged into|part of the .* group)\b", re.IGNORECASE)
_REGULATORY_DEP_RE = re.compile(
    r"\b(subject to (?:regulatory )?approval|pending (?:ce|fda|regulatory) (?:mark|clearance|approval)|"
    r"awaiting certification|requires a licen[cs]e to operate|regulated entity)\b", re.IGNORECASE,
)


def detect_red_flags(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
) -> list[RedFlag]:
    flags: list[RedFlag] = []
    text = " ".join(
        p for p in [startup.product_summary, startup.business_model, startup.technology,
                    startup.technical_moat, startup.market_size_signal,
                    "; ".join(startup.traction_signals), startup.notes] if p
    )

    def ids(*fields: str) -> list[str]:
        return evidence.evidence_ids_for(startup, *fields) if evidence else []

    # --- funding ----------------------------------------------------------
    if startup.total_funding_eur is None:
        flags.append(RedFlag(
            code="funding_unverifiable",
            title="Funding cannot be verified",
            detail=(
                "No total-funding figure could be established. The company is therefore NOT "
                "assumed to be under the thesis ceiling."
            ),
            severity=RedFlagSeverity.HIGH,
            evidence_ids=ids("total_funding_eur"),
        ))
    else:
        if startup.funding_status != VerificationStatus.VERIFIED:
            flags.append(RedFlag(
                code="funding_unverified_source",
                title="Funding figure has no credible source",
                detail=(
                    f"€{startup.total_funding_eur:,.0f} is recorded but its status is "
                    f"{startup.funding_status.value}. Attach a funding announcement before relying on it."
                ),
                severity=RedFlagSeverity.MEDIUM,
                evidence_ids=ids("total_funding_eur"),
            ))
        if startup.total_funding_eur >= thesis.max_total_funding_eur:
            flags.append(RedFlag(
                code="funding_above_ceiling",
                title=f"More than €{thesis.max_total_funding_eur:,.0f} raised",
                detail=f"€{startup.total_funding_eur:,.0f} total funding is at or above the thesis ceiling.",
                severity=RedFlagSeverity.HIGH,
                evidence_ids=ids("total_funding_eur"),
            ))

    if evidence and evidence.has_conflict(startup.id, "total_funding_eur"):
        flags.append(RedFlag(
            code="conflicting_funding_data",
            title="Conflicting funding data",
            detail="Sources disagree on how much this company has raised. Reconcile before proceeding.",
            severity=RedFlagSeverity.HIGH,
            evidence_ids=ids("total_funding_eur"),
        ))

    # --- business model ---------------------------------------------------
    if not startup.business_model:
        flags.append(RedFlag(
            code="unclear_business_model",
            title="Unclear business model",
            detail="No business model is recorded, so revenue quality cannot be assessed.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("business_model"),
        ))
    elif _CONSULTING_RE.search(text) and _SAAS_RE.search(text):
        flags.append(RedFlag(
            code="consulting_as_saas",
            title="Consulting business presented as SaaS",
            detail=(
                "The description mixes product language with services language. Check what share "
                "of revenue is genuinely recurring."
            ),
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("business_model", "product_summary"),
        ))
    elif _CONSULTING_RE.search(text):
        flags.append(RedFlag(
            code="services_business",
            title="Looks like a services business",
            detail="Delivery language dominates; margins and scalability may be limited.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("business_model"),
        ))

    # --- market and moat --------------------------------------------------
    if _CROWDED_RE.search(text) or len(startup.competitors) >= 6:
        flags.append(RedFlag(
            code="crowded_market",
            title="Extremely crowded market",
            detail=(
                f"{len(startup.competitors)} competitors recorded"
                if startup.competitors else "The material itself describes a crowded market."
            ),
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("competitors"),
        ))

    if not startup.technical_moat:
        flags.append(RedFlag(
            code="weak_technical_moat",
            title="Weak or undescribed technical moat",
            detail="No defensibility marker (IP, proprietary data, regulatory barrier, lock-in) was found.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("technical_moat", "technology"),
        ))

    # --- team -------------------------------------------------------------
    if not startup.founders and not startup.founder_background:
        flags.append(RedFlag(
            code="no_founder_market_fit",
            title="No visible founder-market fit",
            detail="Neither founder names nor background information are available.",
            severity=RedFlagSeverity.HIGH,
            evidence_ids=ids("founders", "founder_background"),
        ))
    elif startup.founder_background and not startup.founders:
        flags.append(RedFlag(
            code="founders_unnamed",
            title="Founders are not named",
            detail="A background is described but no individual is named — hard to diligence.",
            severity=RedFlagSeverity.INFO,
            evidence_ids=ids("founders"),
        ))

    # --- traction ---------------------------------------------------------
    if not startup.traction_signals and not startup.customers:
        flags.append(RedFlag(
            code="no_traction_evidence",
            title="No traction evidence",
            detail="Nothing indicates that anyone is using or paying for the product yet.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("traction_signals", "customers"),
        ))
    elif len(startup.customers) == 1:
        flags.append(RedFlag(
            code="customer_concentration",
            title="Customer concentration",
            detail=f"Only one customer is recorded ({startup.customers[0]}). Check revenue concentration.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("customers"),
        ))

    # --- regulatory and status -------------------------------------------
    if _REGULATORY_DEP_RE.search(text):
        flags.append(RedFlag(
            code="regulatory_dependency",
            title="Major regulatory dependency",
            detail="Commercialisation appears to depend on an approval that has not been granted yet.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("technology", "product_summary"),
        ))

    if startup.is_active is False:
        flags.append(RedFlag(
            code="company_inactive",
            title="Company appears inactive",
            detail="The record marks this company as not operating.",
            severity=RedFlagSeverity.HIGH,
            evidence_ids=ids("is_active"),
        ))
    elif startup.website and startup.is_active is None:
        flags.append(RedFlag(
            code="website_unchecked",
            title="Website status unchecked",
            detail="The site was never fetched, so an inactive website would not have been detected.",
            severity=RedFlagSeverity.INFO,
            evidence_ids=ids("website"),
        ))

    if _ACQUIRED_RE.search(text):
        flags.append(RedFlag(
            code="already_acquired",
            title="Company may already be acquired",
            detail="Acquisition language appears in the available text.",
            severity=RedFlagSeverity.HIGH,
        ))

    # --- staleness --------------------------------------------------------
    if startup.last_round_date:
        months = (date.today() - startup.last_round_date).days / 30.4
        if months > 30:
            flags.append(RedFlag(
                code="stale_round",
                title="Last round is old",
                detail=f"Last round closed ~{months:.0f} months ago — the company may have moved stage.",
                severity=RedFlagSeverity.INFO,
                evidence_ids=ids("last_round_date"),
            ))

    if startup.stage == Stage.UNKNOWN:
        flags.append(RedFlag(
            code="stage_unknown",
            title="Stage unknown",
            detail="Without a stage, thesis fit on stage cannot be confirmed.",
            severity=RedFlagSeverity.MEDIUM,
            evidence_ids=ids("stage"),
        ))

    return flags


def apply_red_flags(
    startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager | None = None
) -> Startup:
    """Detect flags, preserving any the investor has already dismissed."""
    dismissed = {f.code for f in startup.red_flags if f.dismissed_by_human}
    manual = [f for f in startup.red_flags if f.source == "human_override"]
    fresh = detect_red_flags(startup, thesis, evidence)
    for flag in fresh:
        if flag.code in dismissed:
            flag.dismissed_by_human = True
    startup.red_flags = fresh + manual
    startup.touch()
    return startup


def open_questions_from_flags(startup: Startup) -> list[str]:
    """Turn the active flags into diligence questions worth asking a founder."""
    templates = {
        "funding_unverifiable": "Exactly how much have you raised to date, and from whom?",
        "funding_unverified_source": "Can you point me to the announcement or cap table summary for your last round?",
        "funding_above_ceiling": "What was the structure of your funding to date — is any of it non-dilutive?",
        "conflicting_funding_data": "Public sources disagree on your total raised — which figure is correct?",
        "unclear_business_model": "How exactly do you charge, and what does a typical contract look like?",
        "consulting_as_saas": "What share of last year's revenue was recurring software versus services?",
        "services_business": "What is the path from delivery work to a repeatable product?",
        "crowded_market": "Who do you lose deals to, and why?",
        "weak_technical_moat": "What would it take a well-funded competitor to replicate this in 12 months?",
        "no_founder_market_fit": "What in your background makes this specific problem yours to solve?",
        "no_traction_evidence": "Who is using the product today, and what did they do before you?",
        "customer_concentration": "What share of revenue does your largest customer represent?",
        "regulatory_dependency": "Which approvals are outstanding, and what is the expected timeline?",
        "company_inactive": "Is the company still operating?",
        "already_acquired": "Has there been any change of ownership or control?",
        "stale_round": "What has changed since your last round, and what is your current runway?",
        "stage_unknown": "Which round are you raising, and what has closed so far?",
    }
    questions: list[str] = []
    for flag in startup.red_flags:
        if flag.dismissed_by_human:
            continue
        q = templates.get(flag.code)
        if q and q not in questions:
            questions.append(q)
    return questions
