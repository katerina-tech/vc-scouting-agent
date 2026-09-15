"""The confidence system.

Confidence is a function of *source quality* and *source agreement*, never of
how fluent an answer sounds. The rules:

* HIGH       — two or more independent Tier-1/Tier-2 sources agree, or a human
               has explicitly marked the field verified.
* MEDIUM     — one credible (Tier-1/Tier-2) source, or several Tier-3 sources
               that agree.
* LOW        — indirect evidence, a single weak source, or a model inference.
* UNVERIFIED — nothing usable at all.

Disagreement between sources never raises confidence; it lowers it and raises a
``conflicting_funding_data``-style red flag upstream.
"""

from __future__ import annotations

from ..models.enums import ConfidenceLevel, SourceTier, VerificationStatus
from ..models.evidence import Evidence, FieldAssessment, level_from_score


def _independent_sources(evidences: list[Evidence]) -> int:
    """Count distinct source hosts, so three links to one article count once."""
    hosts: set[str] = set()
    for ev in evidences:
        if ev.source_url:
            host = ev.source_url.split("//")[-1].split("/")[0].lower()
            hosts.add(host)
        elif ev.source_title:
            hosts.add(ev.source_title.strip().lower())
    return len(hosts)


def values_agree(evidences: list[Evidence]) -> bool:
    """Whether the recorded values are compatible with one another."""
    values = [ev.value for ev in evidences if ev.value not in (None, "", [])]
    if len(values) < 2:
        return True
    numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(numeric) == len(values):
        low, high = min(numeric), max(numeric)
        if high == 0:
            return True
        return (high - low) / abs(high) <= 0.10  # within 10% counts as agreement
    texts = {str(v).strip().lower() for v in values}
    return len(texts) == 1


def assess_field(field_name: str, value, evidences: list[Evidence]) -> FieldAssessment:
    """Combine all evidence for one field into a single displayable verdict."""
    relevant = [ev for ev in evidences if ev.field_name == field_name]

    if not relevant:
        has_value = value not in (None, "", [], {})
        return FieldAssessment(
            field_name=field_name,
            value=value,
            verification_status=(
                VerificationStatus.UNVERIFIED if has_value else VerificationStatus.MISSING
            ),
            confidence=0.1 if has_value else 0.0,
            confidence_level=ConfidenceLevel.UNVERIFIED,
            note=(
                "A value exists but no source was recorded."
                if has_value
                else "No value and no evidence."
            ),
        )

    human = [ev for ev in relevant if ev.human_verified]
    strong = [
        ev for ev in relevant
        if ev.source_tier in (SourceTier.TIER_1, SourceTier.TIER_2) and ev.source_url
    ]
    mid = [ev for ev in relevant if ev.source_tier == SourceTier.TIER_3]
    agree = values_agree(relevant)
    independent = _independent_sources(relevant)

    if human:
        score, status, note = 0.97, VerificationStatus.VERIFIED, "Marked verified by the investor."
    elif strong and independent >= 2 and agree:
        score = min(0.96, max(ev.confidence for ev in strong) + 0.06)
        status = VerificationStatus.VERIFIED
        note = f"{independent} independent credible sources agree."
    elif strong:
        score = max(ev.confidence for ev in strong)
        status = VerificationStatus.VERIFIED
        note = "One credible source."
    elif mid and len(mid) >= 2 and agree:
        score = 0.6
        status = VerificationStatus.UNVERIFIED
        note = "Several weaker sources agree — treat as indicative, not confirmed."
    else:
        best = max(relevant, key=lambda ev: ev.confidence)
        score = min(best.confidence, 0.45)
        status = (
            VerificationStatus.INFERRED
            if best.verification_status == VerificationStatus.INFERRED
            else VerificationStatus.UNVERIFIED
        )
        note = "Indirect evidence or model inference only."

    if not agree:
        score = min(score, 0.4)
        status = VerificationStatus.UNVERIFIED
        note = "⚠️ Sources disagree on this value — reconcile before relying on it."

    return FieldAssessment(
        field_name=field_name,
        value=value,
        verification_status=status,
        confidence=round(score, 3),
        confidence_level=level_from_score(score),
        evidence_ids=[ev.id for ev in relevant],
        evidence=relevant,
        note=note,
    )


#: Fields that drive the headline "data confidence" badge on a company.
KEY_FIELDS: tuple[str, ...] = (
    "total_funding_eur",
    "stage",
    "hq_country",
    "founded_year",
    "product_summary",
    "founders",
)


def overall_confidence(assessments: list[FieldAssessment]) -> tuple[float, ConfidenceLevel]:
    """Average confidence across the key fields (missing fields count as zero)."""
    if not assessments:
        return 0.0, ConfidenceLevel.UNVERIFIED
    score = sum(a.confidence for a in assessments) / len(assessments)
    return round(score, 3), level_from_score(score)


def describe_level(level: ConfidenceLevel) -> str:
    return {
        ConfidenceLevel.HIGH: "Multiple reliable sources agree.",
        ConfidenceLevel.MEDIUM: "One credible source, or several weaker sources.",
        ConfidenceLevel.LOW: "Indirect evidence or inference.",
        ConfidenceLevel.UNVERIFIED: "No reliable evidence.",
    }[level]
