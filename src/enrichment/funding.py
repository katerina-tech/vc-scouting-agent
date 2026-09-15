"""Funding signal extraction.

This is the most dangerous field in the product, so it is the most conservative
module. It will:

* flag when a text mentions a round it can parse, and record it as an
  UNVERIFIED *candidate* for the investor to confirm
* detect conflicts between a mentioned amount and the stored amount

It will never overwrite ``total_funding_eur`` from marketing prose, and never
upgrade a funding figure to VERIFIED without a Tier-1/Tier-2 source URL.
"""

from __future__ import annotations

import re

from ..models.enums import SourceType, VerificationStatus
from ..models.startup import Startup
from ..normalization.company_normalizer import normalize_funding, normalize_stage
from ..research.evidence_manager import EvidenceManager

_ROUND_RE = re.compile(
    r"(?P<context>(?:raised|raising|secured|closed|backed with|funding of|round of)\s+"
    r"(?P<amount>[€$£]?\s?\d[\d.,\s]*\s?(?:k|m|mn|mio|bn|million|billion)?\b"
    r"(?:\s?(?:eur|usd|gbp|chf|sek|nok|dkk|pln))?))",
    flags=re.IGNORECASE,
)

_STAGE_MENTION_RE = re.compile(
    r"\b(pre-?seed|seed round|seed funding|series\s+[a-d])\b", flags=re.IGNORECASE
)

_UNDISCLOSED_RE = re.compile(r"\bundisclosed (?:amount|sum|round)\b", flags=re.IGNORECASE)


def extract_funding_signals(
    startup: Startup, corpus: str, evidence: EvidenceManager, source_url: str | None = None
) -> list[str]:
    notes: list[str] = []
    if not corpus:
        return notes

    for match in _ROUND_RE.finditer(corpus):
        parsed = normalize_funding(match.group("amount"))
        if parsed["amount_eur"] is None:
            continue
        amount = parsed["amount_eur"]
        evidence.record(
            startup.id, "total_funding_eur", amount,
            source_url=source_url, source_title="Text mention",
            source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
            verification_status=VerificationStatus.UNVERIFIED,
            note=(
                f"Candidate funding figure found in text: “{match.group('context').strip()}”. "
                "NOT applied to the company record — confirm against a funding announcement."
            ),
            added_by="enrichment.funding",
        )
        if startup.total_funding_eur is not None and abs(amount - startup.total_funding_eur) > max(
            0.1 * startup.total_funding_eur, 50_000
        ):
            notes.append(
                f"⚠️ Conflicting funding data: record says €{startup.total_funding_eur:,.0f}, "
                f"text mentions €{amount:,.0f}."
            )
        else:
            notes.append(f"Funding figure mentioned in text: €{amount:,.0f} (unverified candidate).")
        break  # one candidate is enough to prompt a human check

    if _UNDISCLOSED_RE.search(corpus):
        notes.append("Text mentions an undisclosed round — total funding cannot be confirmed.")
        evidence.record(
            startup.id, "total_funding_eur", None,
            source_url=source_url, source_type=SourceType.COMPANY_WEBSITE,
            verification_status=VerificationStatus.UNVERIFIED,
            note="An undisclosed round is mentioned; the total raised is not knowable from this source.",
            added_by="enrichment.funding",
        )

    stage_match = _STAGE_MENTION_RE.search(corpus)
    if stage_match and startup.stage.value == "UNKNOWN":
        stage = normalize_stage(stage_match.group(1))
        if stage.value != "UNKNOWN":
            evidence.record(
                startup.id, "stage", stage.value,
                source_url=source_url, source_title="Text mention",
                source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
                verification_status=VerificationStatus.INFERRED,
                note=f"Stage inferred from the phrase “{stage_match.group(1)}”.",
                added_by="enrichment.funding",
            )
            notes.append(f"Stage inferred from text: {stage.label} (inferred, not confirmed).")

    return notes


def funding_is_usable(startup: Startup) -> bool:
    """Whether the funding figure is solid enough to drive eligibility."""
    return (
        startup.total_funding_eur is not None
        and startup.funding_status == VerificationStatus.VERIFIED
    )
