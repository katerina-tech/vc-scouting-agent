"""Duplicate detection and merging.

The same company arrives from a CSV, a manual entry and a URL paste. We match
on *domain first* (strongest signal), then on the normalized company name.
Merging is evidence-preserving: the record with better-verified data wins each
field, and every source URL from every copy is kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.enums import Stage, VerificationStatus
from ..models.startup import Startup
from .company_normalizer import extract_domain, normalize_company_name

_VERIFICATION_RANK = {
    VerificationStatus.VERIFIED: 3,
    VerificationStatus.INFERRED: 2,
    VerificationStatus.UNVERIFIED: 1,
    VerificationStatus.MISSING: 0,
}

#: Fields merged by "first non-empty wins, preferring the richer record".
_SCALAR_FIELDS = (
    "website", "domain", "hq_country", "hq_country_raw", "city", "founded_year",
    "sector", "subsector", "stage_raw", "founder_background", "product_summary",
    "business_model", "technology", "technical_moat", "market_size_signal",
    "impact_signal", "why_now_signal", "last_round_date", "last_round_eur",
    "last_round_raw", "fx_note", "is_active", "notes",
)

_LIST_FIELDS = (
    "themes", "investors", "founders", "customers", "traction_signals",
    "competitors", "source_urls", "open_questions", "investor_notes",
)


@dataclass
class DuplicateGroup:
    key: str
    match_reason: str
    members: list[Startup] = field(default_factory=list)


@dataclass
class DeduplicationReport:
    merged_count: int = 0
    groups: list[DuplicateGroup] = field(default_factory=list)

    @property
    def messages(self) -> list[str]:
        out = []
        for group in self.groups:
            if len(group.members) < 2:
                continue
            names = ", ".join(sorted({m.company_name for m in group.members}))
            out.append(f"Merged {len(group.members)} records ({group.match_reason}): {names}")
        return out


def dedup_key(startup: Startup) -> tuple[str, str]:
    """Return ``(key, reason)`` — domain when available, else normalized name."""
    domain = startup.domain or extract_domain(startup.website)
    if domain:
        return f"domain:{domain}", "same website domain"
    name_key = startup.normalized_name or normalize_company_name(startup.company_name)
    return f"name:{name_key}", "same normalized company name"


def _richness(startup: Startup) -> int:
    """Crude completeness score used to decide which record is the base."""
    score = 0
    for f in _SCALAR_FIELDS:
        if getattr(startup, f, None) not in (None, "", []):
            score += 1
    for f in _LIST_FIELDS:
        score += min(len(getattr(startup, f, []) or []), 3)
    if startup.total_funding_eur is not None:
        score += 2
    score += _VERIFICATION_RANK[startup.funding_status]
    return score


def merge_pair(base: Startup, other: Startup) -> Startup:
    """Merge ``other`` into ``base`` without losing provenance."""
    for f in _SCALAR_FIELDS:
        if getattr(base, f, None) in (None, "", []):
            value = getattr(other, f, None)
            if value not in (None, "", []):
                setattr(base, f, value)

    for f in _LIST_FIELDS:
        combined = list(getattr(base, f, []) or [])
        seen = {str(v).strip().lower() for v in combined}
        for value in getattr(other, f, []) or []:
            key = str(value).strip().lower()
            if key and key not in seen:
                combined.append(value)
                seen.add(key)
        setattr(base, f, combined)

    # Funding: the better-verified figure wins; a tie keeps the existing one.
    if _VERIFICATION_RANK[other.funding_status] > _VERIFICATION_RANK[base.funding_status]:
        base.total_funding_eur = other.total_funding_eur
        base.total_funding_raw = other.total_funding_raw
        base.funding_status = other.funding_status
    elif base.total_funding_eur is None and other.total_funding_eur is not None:
        base.total_funding_eur = other.total_funding_eur
        base.total_funding_raw = other.total_funding_raw
        base.funding_status = other.funding_status

    if base.stage == Stage.UNKNOWN and other.stage != Stage.UNKNOWN:
        base.stage = other.stage

    base.raw_record.setdefault("merged_from", []).append(
        {"id": other.id, "company_name": other.company_name, "adapter": other.source_adapter}
    )
    base.human_overrides.extend(other.human_overrides)
    base.shortlisted = base.shortlisted or other.shortlisted
    base.manual_eligibility_approved = (
        base.manual_eligibility_approved or other.manual_eligibility_approved
    )
    base.touch()
    return base


def deduplicate(startups: list[Startup]) -> tuple[list[Startup], DeduplicationReport]:
    """Collapse duplicates. Demo and real companies are never merged together."""
    report = DeduplicationReport()
    buckets: dict[tuple[str, str], DuplicateGroup] = {}

    for startup in startups:
        key, reason = dedup_key(startup)
        bucket_key = (startup.dataset.value, key)
        group = buckets.get(bucket_key)
        if group is None:
            buckets[bucket_key] = DuplicateGroup(key=key, match_reason=reason, members=[startup])
        else:
            group.members.append(startup)

    merged: list[Startup] = []
    for group in buckets.values():
        report.groups.append(group)
        if len(group.members) == 1:
            merged.append(group.members[0])
            continue
        ordered = sorted(group.members, key=_richness, reverse=True)
        base = ordered[0]
        for other in ordered[1:]:
            base = merge_pair(base, other)
            report.merged_count += 1
        merged.append(base)

    return merged, report


def find_existing(startup: Startup, existing: list[Startup]) -> Startup | None:
    """Locate an already-stored record that represents the same company."""
    key, _ = dedup_key(startup)
    for candidate in existing:
        if candidate.dataset != startup.dataset:
            continue
        if dedup_key(candidate)[0] == key:
            return candidate
    return None
