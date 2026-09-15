"""In-memory index over all evidence, with helpers the UI and scorer share.

The manager is the only place that decides what a field's verification status
is — so "what do we actually know about this company?" has exactly one answer
everywhere in the application.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from ..models.enums import (
    ConfidenceLevel,
    SourceType,
    VerificationStatus,
)
from ..models.evidence import Evidence, FieldAssessment
from ..models.startup import Startup
from .confidence import KEY_FIELDS, assess_field, overall_confidence, values_agree


class EvidenceManager:
    """Holds every ``Evidence`` row and answers questions about fields."""

    def __init__(self, evidences: list[Evidence] | None = None) -> None:
        self._by_startup: dict[str, list[Evidence]] = defaultdict(list)
        self._by_id: dict[str, Evidence] = {}
        for ev in evidences or []:
            self.add(ev)

    # ---------------------------------------------------------------- CRUD
    def add(self, evidence: Evidence) -> Evidence:
        self._by_startup[evidence.startup_id].append(evidence)
        self._by_id[evidence.id] = evidence
        return evidence

    def add_many(self, evidences: list[Evidence]) -> None:
        for ev in evidences:
            self.add(ev)

    def record(
        self,
        startup_id: str,
        field_name: str,
        value,
        *,
        source_url: str | None = None,
        source_title: str | None = None,
        source_type: SourceType = SourceType.USER_INPUT,
        verification_status: VerificationStatus = VerificationStatus.UNVERIFIED,
        note: str = "",
        confidence: float | None = None,
        added_by: str = "system",
    ) -> Evidence:
        """Convenience constructor used by loaders, enrichment and the UI."""
        kwargs: dict = dict(
            startup_id=startup_id,
            field_name=field_name,
            value=value,
            source_url=source_url,
            source_title=source_title,
            source_type=source_type,
            verification_status=verification_status,
            evidence_note=note,
            added_by=added_by,
        )
        if confidence is not None:
            kwargs["confidence"] = confidence
        return self.add(Evidence(**kwargs))

    def get(self, evidence_id: str) -> Evidence | None:
        return self._by_id.get(evidence_id)

    def all(self) -> list[Evidence]:
        return list(self._by_id.values())

    def for_startup(self, startup_id: str) -> list[Evidence]:
        return list(self._by_startup.get(startup_id, []))

    def for_field(self, startup_id: str, field_name: str) -> list[Evidence]:
        return [ev for ev in self.for_startup(startup_id) if ev.field_name == field_name]

    def by_ids(self, ids: list[str]) -> list[Evidence]:
        return [self._by_id[i] for i in ids if i in self._by_id]

    def remove_for_startup(self, startup_id: str) -> None:
        for ev in self._by_startup.pop(startup_id, []):
            self._by_id.pop(ev.id, None)

    # ------------------------------------------------------- human-in-loop
    def mark_verified(self, evidence_id: str, verified: bool = True) -> Evidence | None:
        ev = self._by_id.get(evidence_id)
        if ev is None:
            return None
        updated = ev.model_copy(update={"human_verified": verified})
        if not verified:
            updated = updated.model_copy(
                update={"verification_status": VerificationStatus.UNVERIFIED}
            )
        updated = Evidence(**updated.model_dump())
        self._by_id[evidence_id] = updated
        bucket = self._by_startup[ev.startup_id]
        for i, item in enumerate(bucket):
            if item.id == evidence_id:
                bucket[i] = updated
                break
        return updated

    def add_source(
        self,
        startup_id: str,
        field_name: str,
        value,
        source_url: str,
        source_title: str,
        source_type: SourceType,
        note: str = "",
        author: str = "investor",
    ) -> Evidence:
        """An investor adding a source they found themselves."""
        return self.record(
            startup_id,
            field_name,
            value,
            source_url=source_url,
            source_title=source_title,
            source_type=source_type,
            verification_status=VerificationStatus.VERIFIED,
            note=note or "Added manually by the investor.",
            added_by=author,
        )

    # ----------------------------------------------------------- questions
    def assess(self, startup: Startup, field_name: str, value=None) -> FieldAssessment:
        if value is None:
            value = getattr(startup, field_name, None)
        return assess_field(field_name, value, self.for_startup(startup.id))

    def assess_many(self, startup: Startup, fields: tuple[str, ...]) -> dict[str, FieldAssessment]:
        return {f: self.assess(startup, f) for f in fields}

    def status_of(self, startup: Startup, field_name: str) -> VerificationStatus:
        return self.assess(startup, field_name).verification_status

    def confidence_of(self, startup: Startup, field_name: str) -> float:
        return self.assess(startup, field_name).confidence

    def evidence_ids_for(self, startup: Startup, *fields: str) -> list[str]:
        ids: list[str] = []
        for f in fields:
            ids.extend(ev.id for ev in self.for_field(startup.id, f))
        return ids

    def has_conflict(self, startup_id: str, field_name: str) -> bool:
        evidences = self.for_field(startup_id, field_name)
        return len(evidences) > 1 and not values_agree(evidences)

    def refresh_startup_confidence(self, startup: Startup) -> Startup:
        """Recompute the headline data-confidence badge and funding status."""
        assessments = [self.assess(startup, f) for f in KEY_FIELDS]
        _, level = overall_confidence(assessments)
        startup.data_confidence = level

        funding = self.assess(startup, "total_funding_eur")
        if startup.total_funding_eur is None:
            startup.funding_status = VerificationStatus.MISSING
        else:
            startup.funding_status = funding.verification_status

        urls = sorted({ev.source_url for ev in self.for_startup(startup.id) if ev.source_url})
        for url in urls:
            if url not in startup.source_urls:
                startup.source_urls.append(url)

        startup.touch()
        return startup

    def summary_counts(self, startup_id: str) -> dict[str, int]:
        counts = {s.value: 0 for s in VerificationStatus}
        for ev in self.for_startup(startup_id):
            counts[ev.verification_status.value] += 1
        return counts

    def freshness(self, startup_id: str) -> str:
        evidences = self.for_startup(startup_id)
        if not evidences:
            return "No evidence recorded."
        newest = max(ev.retrieved_at for ev in evidences)
        age_days = (datetime.now(timezone.utc) - newest).days
        return f"Most recent evidence retrieved {age_days} day(s) ago."


def default_confidence_legend() -> list[tuple[ConfidenceLevel, str]]:
    from .confidence import describe_level

    return [(level, describe_level(level)) for level in ConfidenceLevel]
