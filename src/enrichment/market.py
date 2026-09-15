"""Market and "why now" signals.

Market size claims are recorded as claims. Timing signals are extracted from
explicit regulatory / cost-curve / behavioural language — the app does not
pretend to know why now if the text does not say.
"""

from __future__ import annotations

import re

from ..models.enums import SourceType, VerificationStatus
from ..models.startup import Startup
from ..research.evidence_manager import EvidenceManager

_MARKET_SIZE_RE = re.compile(
    r"\b([€$£]\s?\d[\d.,]*\s*(?:bn|b|billion|m|mn|million|trillion|tn))\s*"
    r"(?:\w+\s+){0,3}?(market|tam|sam|som|opportunity|industry|spend)\b",
    re.IGNORECASE,
)
_REGULATION_RE = re.compile(
    r"\b(csrd|cbam|eu taxonomy|ai act|mdr|dora|psd2|psd3|green deal|fit for 55|"
    r"eudr|reach|repowereu|deforestation regulation|right to repair|nis2)\b",
    re.IGNORECASE,
)
_TIMING_RE = re.compile(
    r"\b(cost of \w+ (?:has )?(?:fallen|dropped|collapsed)|newly (?:mandated|required)|"
    r"from 202\d, |deadline of 202\d|comes into force|mandatory from|now required to report)\b",
    re.IGNORECASE,
)
_IMPACT_RE = re.compile(
    r"\b(tonnes? of co2|tco2e|co2e|emissions? avoided|patients? treated|people reached|"
    r"households served|kwh saved|water saved|jobs created|sdg\s?\d{1,2})\b",
    re.IGNORECASE,
)
_CROWDED_RE = re.compile(
    r"\b(crowded (?:market|space)|many competitors|dozens of (?:players|startups)|commoditi[sz]ed)\b",
    re.IGNORECASE,
)


def extract_market_signals(
    startup: Startup, corpus: str, evidence: EvidenceManager, source_url: str | None = None
) -> list[str]:
    notes: list[str] = []
    text = " ".join(
        p for p in [corpus, startup.market_size_signal, startup.impact_signal, startup.why_now_signal] if p
    )
    if not text.strip():
        return notes

    size = _MARKET_SIZE_RE.search(text)
    if size:
        claim = size.group(0).strip()
        if not startup.market_size_signal:
            startup.market_size_signal = claim
        evidence.record(
            startup.id, "market_size_signal", claim,
            source_url=source_url, source_title="Market size claim",
            source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
            verification_status=VerificationStatus.UNVERIFIED,
            note="Market-size figure quoted in the company's own material — verify against an analyst source.",
            added_by="enrichment.market",
        )
        notes.append(f"Market size claim found: {claim} (unverified).")

    regs = sorted({m.group(1).upper() for m in _REGULATION_RE.finditer(text)})
    timing = _TIMING_RE.search(text)
    why_now_parts: list[str] = []
    if regs:
        why_now_parts.append("regulatory driver(s) referenced: " + ", ".join(regs))
    if timing:
        why_now_parts.append(f"timing language: “{timing.group(0).strip()}”")

    if why_now_parts:
        summary = "; ".join(why_now_parts)
        if not startup.why_now_signal:
            startup.why_now_signal = summary
        evidence.record(
            startup.id, "why_now_signal", summary,
            source_url=source_url, source_title="Timing signal",
            source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
            verification_status=VerificationStatus.INFERRED,
            note="Timing rationale derived from explicit regulatory or cost-curve language in the text.",
            added_by="enrichment.market",
        )
        notes.append(f"Why-now signal: {summary}.")

    impacts = sorted({m.group(1).lower() for m in _IMPACT_RE.finditer(text)})
    if impacts:
        claim = "measurable impact units referenced: " + ", ".join(impacts)
        if not startup.impact_signal:
            startup.impact_signal = claim
        evidence.record(
            startup.id, "impact_signal", claim,
            source_url=source_url, source_type=SourceType.COMPANY_WEBSITE if source_url
            else SourceType.LLM_INFERENCE,
            verification_status=VerificationStatus.INFERRED,
            note="Impact wording found in text; no impact figure is verified here.",
            added_by="enrichment.market",
        )
        notes.append(f"Impact signal: {claim}.")

    if _CROWDED_RE.search(text):
        notes.append("Text itself describes a crowded market — check competitive differentiation.")

    return notes
