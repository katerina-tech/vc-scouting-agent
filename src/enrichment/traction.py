"""Traction signals.

Extracts *claimed* traction — named customers, pilot language, user counts,
revenue language, regulatory clearances — and records every one as UNVERIFIED.
A company's own homepage claiming "trusted by 200 clinics" is a claim, not a
metric, and the memo will say so.
"""

from __future__ import annotations

import re

from ..models.enums import SourceType, VerificationStatus
from ..models.startup import Startup
from ..research.evidence_manager import EvidenceManager

_COUNT_RE = re.compile(
    r"\b(\d[\d.,]*\s*(?:k|m)?\+?)\s+(customers|clients|users|patients|hospitals|clinics|"
    r"schools|farms|companies|businesses|partners|installations|sites|downloads|subscribers)\b",
    re.IGNORECASE,
)
_REVENUE_RE = re.compile(r"\b(arr|mrr|annual recurring revenue|revenue run[- ]rate)\b", re.IGNORECASE)
_PILOT_RE = re.compile(r"\b(pilot|proof of concept|poc|trial deployment|lighthouse customer)s?\b", re.IGNORECASE)
_CONTRACT_RE = re.compile(r"\b(loi|letter of intent|framework agreement|multi-year contract|tender)\b", re.IGNORECASE)
_REGULATORY_RE = re.compile(r"\b(ce mark|ce-mark|fda clearance|mdr|iso 13485|gdpr certified|ukca)\b", re.IGNORECASE)
_WAITLIST_RE = re.compile(r"\b(waitlist|wait list|join the beta|coming soon|early access)\b", re.IGNORECASE)


def extract_traction_signals(
    startup: Startup, corpus: str, evidence: EvidenceManager, source_url: str | None = None
) -> list[str]:
    notes: list[str] = []
    text = " ".join(
        p for p in [corpus, "; ".join(startup.traction_signals), "; ".join(startup.customers)] if p
    )
    if not text.strip():
        return notes

    signals: list[str] = []

    for match in list(_COUNT_RE.finditer(text))[:4]:
        signals.append(f"claims {match.group(1).strip()} {match.group(2).lower()}")
    if _REVENUE_RE.search(text):
        signals.append("mentions recurring revenue (ARR/MRR) without a disclosed figure")
    if _PILOT_RE.search(text):
        signals.append("pilot / proof-of-concept language present")
    if _CONTRACT_RE.search(text):
        signals.append("contract or letter-of-intent language present")
    if _REGULATORY_RE.search(text):
        signals.append("regulatory clearance mentioned (CE / FDA / ISO)")
    if _WAITLIST_RE.search(text):
        signals.append("pre-launch language (waitlist / early access) — traction may be aspirational")

    if not signals:
        notes.append("No traction signals found in available text.")
        return notes

    for signal in signals:
        if signal not in startup.traction_signals:
            startup.traction_signals.append(signal)

    evidence.record(
        startup.id, "traction_signals", signals,
        source_url=source_url, source_title="Traction claims in text",
        source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
        verification_status=VerificationStatus.UNVERIFIED,
        note=(
            "Self-reported claims extracted from text. Treat as claims until confirmed by a "
            "customer reference, an invoice, or an independent report."
        ),
        added_by="enrichment.traction",
    )
    notes.append(f"Traction claims found: {'; '.join(signals)}.")
    return notes


def has_hard_traction(startup: Startup) -> bool:
    """Whether anything looks like *named* commercial traction rather than prose."""
    return bool(startup.customers) or any(
        kw in " ".join(startup.traction_signals).lower()
        for kw in ("contract", "revenue", "paying", "letter of intent", "clearance")
    )
