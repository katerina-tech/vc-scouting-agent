"""Founder signals.

Founder-market fit is one of the few things a careful reader can assess from
public text — but only if the text actually exists. This module extracts what
is *stated* (prior employers, degrees, years of domain experience) and records
it as INFERRED. It never invents a CV.
"""

from __future__ import annotations

import re

from ..models.enums import SourceType, VerificationStatus
from ..models.startup import Startup
from ..research.evidence_manager import EvidenceManager

_EXPERIENCE_RE = re.compile(r"\b(\d{1,2})\+?\s*years?\s+(?:of\s+)?(?:experience|in)\b", re.IGNORECASE)
_PRIOR_ROLE_RE = re.compile(
    r"\b(?:previously|formerly|ex-|prior to|before founding)\s+(?:at\s+)?([A-Z][\w&.\- ]{2,40})",
)
_ACADEMIC_RE = re.compile(
    r"\b(phd|dphil|md|professor|postdoc|msc|m\.sc|mba|research fellow)\b", re.IGNORECASE
)
_REPEAT_FOUNDER_RE = re.compile(
    r"\b(second-time founder|repeat founder|serial entrepreneur|previously founded|exited)\b",
    re.IGNORECASE,
)


def extract_founder_signals(
    startup: Startup, corpus: str, evidence: EvidenceManager, source_url: str | None = None
) -> list[str]:
    notes: list[str] = []
    text = " ".join(p for p in [startup.founder_background, corpus] if p)
    if not text.strip():
        return notes

    found: list[str] = []

    years = _EXPERIENCE_RE.search(text)
    if years:
        found.append(f"{years.group(1)}+ years of stated domain experience")

    prior = [m.group(1).strip(" .,") for m in _PRIOR_ROLE_RE.finditer(text)][:3]
    if prior:
        found.append("prior roles mentioned: " + ", ".join(prior))

    academic = sorted({m.group(1).upper() for m in _ACADEMIC_RE.finditer(text)})
    if academic:
        found.append("academic/clinical credentials mentioned: " + ", ".join(academic))

    if _REPEAT_FOUNDER_RE.search(text):
        found.append("repeat-founder language present")

    if not found:
        if not startup.founders:
            notes.append("No founder information available — founder-market fit cannot be scored.")
        return notes

    summary = "; ".join(found)
    evidence.record(
        startup.id, "founder_background", summary,
        source_url=source_url, source_title="Founder text",
        source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
        verification_status=VerificationStatus.INFERRED,
        note="Signals extracted from founder text. Verify against LinkedIn or a primary bio.",
        added_by="enrichment.founders",
    )
    notes.append(f"Founder signals: {summary}.")
    return notes


def founder_market_fit_signals(startup: Startup) -> list[str]:
    """Overlap between founder background and the company's own domain."""
    background = (startup.founder_background or "").lower()
    if not background:
        return []
    domain_words = {
        w for w in re.findall(r"[a-z]{4,}", " ".join(
            p for p in [startup.sector, startup.subsector, startup.technology,
                        startup.product_summary] if p
        ).lower())
    }
    stop = {"platform", "software", "company", "solution", "using", "their", "which",
            "based", "helps", "with", "that", "from", "into", "this", "have"}
    domain_words -= stop
    hits = sorted(w for w in domain_words if w in background)
    return hits[:8]
