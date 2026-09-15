"""Investment memo generation.

The memo is assembled deterministically from the evidence. If an LLM is
configured it writes the prose for each section; if not, the section is filled
from the structured record. Either way the *structure*, the recommendation logic
and the missing-information section are computed, not written by a model.

The recommendation is one of PASS / WATCH / INVESTIGATE. There is deliberately
no INVEST: an automated tool does not get to make that call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..models.enums import EligibilityStatus, Recommendation, RedFlagSeverity
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..llm.investment_analyst import InvestmentAnalyst, MemoSections
from ..llm.prompts import INSUFFICIENT
from ..research.evidence_manager import EvidenceManager
from ..scoring.score_config import (
    MIN_CONFIDENCE_FOR_INVESTIGATE,
    MIN_COVERAGE_FOR_INVESTIGATE,
    RECOMMENDATION_THRESHOLDS,
)

SECTION_ORDER: list[tuple[str, str]] = [
    ("one_line_thesis", "One-line thesis"),
    ("what_the_company_does", "What the company does"),
    ("problem", "Problem"),
    ("why_this_problem_matters", "Why this problem matters"),
    ("why_now", "Why now"),
    ("why_it_fits_the_thesis", "Why this fits the investment thesis"),
    ("market_potential", "Market potential"),
    ("founder_market_fit", "Founder-market fit"),
    ("traction", "Traction"),
    ("technology_and_moat", "Technology / moat"),
    ("impact", "Impact"),
    ("competition", "Competition"),
    ("key_risks", "Key risks"),
    ("missing_information", "Missing information"),
]


@dataclass
class InvestmentMemo:
    startup_id: str
    company: str
    sections: dict[str, str] = field(default_factory=dict)
    questions_for_founders: list[str] = field(default_factory=list)
    recommendation: Recommendation = Recommendation.WATCH
    recommendation_reason: str = ""
    score_total: float | None = None
    evidence_coverage: float = 0.0
    confidence: float = 0.0
    red_flags: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    llm_used: bool = False
    is_demo: bool = False
    generator_note: str = ""

    def to_markdown(self) -> str:
        lines: list[str] = []
        if self.is_demo:
            lines.append("> ⚠️ **DEMO DATA — this is a fictional company created to exercise the tool.**\n")
        lines.append(f"# Investment memo — {self.company}\n")
        lines.append(
            f"*Generated {self.generated_at:%Y-%m-%d %H:%M UTC} · "
            f"{'LLM-assisted' if self.llm_used else 'deterministic (no LLM)'} · "
            f"score {self.score_total if self.score_total is not None else '—'}/100 · "
            f"{self.evidence_coverage:.0%} of the framework assessable · "
            f"confidence {self.confidence:.2f}*\n"
        )
        lines.append(f"**Recommendation: {self.recommendation.label}**\n")
        lines.append(f"> {self.recommendation_reason}\n")

        for key, heading in SECTION_ORDER:
            body = (self.sections.get(key) or INSUFFICIENT).strip()
            lines.append(f"## {heading}\n\n{body}\n")

        if self.red_flags:
            lines.append("## Red flags\n")
            lines.extend(f"- {flag}" for flag in self.red_flags)
            lines.append("")

        if self.questions_for_founders:
            lines.append("## Questions for founders\n")
            lines.extend(f"{i}. {q}" for i, q in enumerate(self.questions_for_founders, 1))
            lines.append("")

        if self.sources:
            lines.append("## Sources\n")
            lines.extend(f"- {url}" for url in self.sources)
            lines.append("")

        lines.append(
            "---\n*This memo structures research. It does not predict investment success, "
            "and no automated recommendation above INVESTIGATE is available by design — "
            "the investment decision is human.*"
        )
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Recommendation
# --------------------------------------------------------------------------- #

def decide_recommendation(startup: Startup) -> tuple[Recommendation, str]:
    """Deterministic, explainable, and capped at INVESTIGATE."""
    score = startup.score_total
    breakdown = startup.score_breakdown
    coverage = breakdown.evidence_coverage if breakdown else 0.0
    confidence = breakdown.confidence if breakdown else 0.0
    high_flags = [f for f in startup.red_flags
                  if f.severity == RedFlagSeverity.HIGH and not f.dismissed_by_human]

    if startup.eligibility_status == EligibilityStatus.INELIGIBLE:
        return Recommendation.PASS_, (
            "The company fails at least one hard eligibility filter: "
            + "; ".join(c.detail for c in (startup.eligibility_result.failed if startup.eligibility_result else []))
        )

    if score is None:
        return Recommendation.WATCH, "No score has been computed yet."

    if high_flags:
        titles = ", ".join(f.title for f in high_flags)
        if score >= RECOMMENDATION_THRESHOLDS["investigate"]:
            return Recommendation.WATCH, (
                f"Scores {score:.0f}/100, but {len(high_flags)} high-severity red flag(s) "
                f"must be resolved first: {titles}."
            )
        return Recommendation.PASS_, (
            f"Scores {score:.0f}/100 with high-severity red flag(s): {titles}."
        )

    medium_flags = [f for f in startup.red_flags
                    if f.severity == RedFlagSeverity.MEDIUM and not f.dismissed_by_human]

    if score >= RECOMMENDATION_THRESHOLDS["investigate"]:
        if len(medium_flags) >= 3:
            return Recommendation.WATCH, (
                f"Scores {score:.0f}/100, but {len(medium_flags)} medium-severity concerns stack "
                f"up ({', '.join(f.title for f in medium_flags[:3])}). The score flatters it — "
                "resolve these before spending partner time."
            )
        if coverage < MIN_COVERAGE_FOR_INVESTIGATE:
            return Recommendation.WATCH, (
                f"Scores {score:.0f}/100 but only {coverage:.0%} of the scoring framework could "
                f"be assessed — too much is unknown to justify partner time yet."
            )
        if confidence < MIN_CONFIDENCE_FOR_INVESTIGATE:
            return Recommendation.WATCH, (
                f"Scores {score:.0f}/100 but the underlying evidence confidence is only "
                f"{confidence:.2f}. Verify the key fields, then revisit."
            )
        return Recommendation.INVESTIGATE, (
            f"Scores {score:.0f}/100 with {coverage:.0%} of the framework assessable and "
            f"evidence confidence {confidence:.2f}. Worth a founder conversation."
        )

    if score >= RECOMMENDATION_THRESHOLDS["watch"]:
        return Recommendation.WATCH, (
            f"Scores {score:.0f}/100 — interesting but not yet compelling. "
            f"Revisit once the open questions are answered."
        )

    return Recommendation.PASS_, (
        f"Scores {score:.0f}/100 against this thesis. Not a fit right now."
    )


# --------------------------------------------------------------------------- #
# Deterministic section text
# --------------------------------------------------------------------------- #

def _deterministic_sections(startup: Startup, thesis: InvestmentThesis) -> dict[str, str]:
    def or_missing(value, template: str) -> str:
        if value in (None, "", [], {}):
            return INSUFFICIENT
        if isinstance(value, (list, tuple)):
            value = "; ".join(str(v) for v in value)
        return template.format(value=value)

    breakdown = startup.score_breakdown
    unscored = ", ".join(c.label for c in breakdown.unscored_criteria) if breakdown else ""

    missing_bits: list[str] = []
    if startup.total_funding_eur is None:
        missing_bits.append("total funding raised")
    if not startup.founders:
        missing_bits.append("founder names")
    if not startup.customers and not startup.traction_signals:
        missing_bits.append("any traction evidence")
    if not startup.business_model:
        missing_bits.append("the business model")
    if not startup.market_size_signal:
        missing_bits.append("an independent market-size estimate")
    if unscored:
        missing_bits.append(f"enough evidence to score: {unscored}")

    return {
        "one_line_thesis": (
            f"{startup.company_name} is a {startup.stage.label.lower()} "
            f"{(startup.sector or 'technology').lower()} company in "
            f"{startup.hq_country or 'an unrecorded country'}"
            + (f" building {startup.product_summary[:120]}" if startup.product_summary else "")
            + "."
        ),
        "what_the_company_does": or_missing(startup.product_summary, "FACT: {value}"),
        "problem": or_missing(
            startup.product_summary,
            "INFERENCE: derived from the company's own description — {value}",
        ),
        "why_this_problem_matters": or_missing(
            startup.impact_signal or startup.market_size_signal, "FACT: {value}"
        ),
        "why_now": or_missing(startup.why_now_signal, "INFERENCE: {value}"),
        "why_it_fits_the_thesis": (
            "FACT: " + "; ".join(startup.eligibility_reasons[:4])
            if startup.eligibility_reasons else INSUFFICIENT
        ),
        "market_potential": or_missing(
            startup.market_size_signal,
            "UNVERIFIED CLAIM: {value} — sourced from the company's own material.",
        ),
        "founder_market_fit": or_missing(
            startup.founder_background,
            "INFERENCE: {value}",
        ) if startup.founder_background else (
            f"FACT: founders recorded as {', '.join(startup.founders)}. No background available."
            if startup.founders else INSUFFICIENT
        ),
        "traction": or_missing(
            startup.traction_signals,
            "UNVERIFIED CLAIMS: {value} — self-reported unless a third-party source is attached.",
        ),
        "technology_and_moat": or_missing(
            startup.technical_moat or startup.technology, "INFERENCE: {value}"
        ),
        "impact": or_missing(startup.impact_signal, "INFERENCE: {value}"),
        "competition": or_missing(
            startup.competitors, "FACT: competitors recorded — {value}."
        ),
        "key_risks": (
            "; ".join(f"{f.severity.value}: {f.title} — {f.detail}"
                      for f in startup.red_flags if not f.dismissed_by_human)
            or "No red flags were detected, which is itself worth checking."
        ),
        "missing_information": (
            "Before any real decision this memo still needs: " + "; ".join(missing_bits) + "."
            if missing_bits else "The core fields are all populated; verify the sources next."
        ),
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def generate_memo(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
    analyst: InvestmentAnalyst | None = None,
) -> InvestmentMemo:
    """Build the memo, LLM-assisted when available and deterministic otherwise."""
    sections = _deterministic_sections(startup, thesis)
    llm_used = False
    note = "Sections written deterministically from the evidence record."

    if analyst is not None and analyst.available:
        result = analyst.memo_sections(startup, thesis, evidence)
        if result.available and isinstance(result.data, MemoSections):
            llm_sections = result.data.model_dump()
            for key, value in llm_sections.items():
                text = (value or "").strip()
                # Never let an empty or evasive LLM section overwrite real data.
                if text and text != INSUFFICIENT:
                    sections[key] = text
                elif sections.get(key) in (None, "", INSUFFICIENT):
                    sections[key] = INSUFFICIENT
            llm_used = True
            note = "Narrative sections drafted by the analyst model from the evidence dossier."
        else:
            note = f"LLM draft unavailable ({result.note}). Fell back to deterministic sections."

    questions = list(startup.open_questions)
    if analyst is not None:
        q_result = analyst.founder_questions(startup, evidence)
        for q in (q_result.data or []):
            if q not in questions:
                questions.append(q)

    recommendation, reason = decide_recommendation(startup)
    breakdown = startup.score_breakdown

    memo = InvestmentMemo(
        startup_id=startup.id,
        company=startup.company_name,
        sections=sections,
        questions_for_founders=questions[:10],
        recommendation=recommendation,
        recommendation_reason=reason,
        score_total=startup.score_total,
        evidence_coverage=breakdown.evidence_coverage if breakdown else 0.0,
        confidence=breakdown.confidence if breakdown else 0.0,
        red_flags=[f"{f.severity.label} **{f.title}** — {f.detail}"
                   for f in startup.red_flags if not f.dismissed_by_human],
        sources=list(dict.fromkeys(startup.source_urls)),
        llm_used=llm_used,
        is_demo=startup.is_demo,
        generator_note=note,
    )
    startup.recommendation = recommendation
    return memo
