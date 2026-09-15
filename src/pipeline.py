"""The orchestration layer: ingest → normalize → dedup → enrich → filter → score.

Keeping this here (rather than in ``app.py``) means the whole pipeline is
testable and reusable from a script or a notebook, and the Streamlit layer stays
a thin presentation shell.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enrichment.company_enrichment import enrich_company
from .filters.eligibility import apply_eligibility
from .ingestion.source_adapter import IngestionResult
from .models.enums import Dataset
from .models.startup import Startup
from .models.thesis import InvestmentThesis
from .normalization.deduplication import deduplicate, find_existing, merge_pair
from .research.evidence_manager import EvidenceManager
from .research.red_flags import apply_red_flags, open_questions_from_flags
from .scoring.score_engine import apply_score, rank
from .storage.repository import Repository


@dataclass
class PipelineReport:
    ingested: int = 0
    added: int = 0
    merged: int = 0
    skipped: int = 0
    eligible: int = 0
    needs_review: int = 0
    ineligible: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        return (
            f"{self.ingested} row(s) read · {self.added} added · {self.merged} merged into "
            f"existing records · {self.eligible} eligible · {self.needs_review} need review · "
            f"{self.ineligible} ineligible"
        )


def assess_one(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager,
    *,
    enrich: bool = True,
) -> list[str]:
    """Run enrichment, eligibility, scoring and red flags over one company."""
    notes: list[str] = []
    if enrich:
        notes.extend(enrich_company(startup, evidence))
    else:
        evidence.refresh_startup_confidence(startup)

    apply_eligibility(startup, thesis, evidence)
    apply_score(startup, thesis, evidence)
    apply_red_flags(startup, thesis, evidence)

    for question in open_questions_from_flags(startup):
        if question not in startup.open_questions:
            startup.open_questions.append(question)
    return notes


def reassess_all(
    repo: Repository,
    thesis: InvestmentThesis,
    evidence: EvidenceManager,
    dataset: Dataset | None = None,
    *,
    enrich: bool = False,
) -> PipelineReport:
    """Re-run eligibility and scoring for every stored company under a new thesis."""
    report = PipelineReport()
    for startup in repo.list_startups(dataset):
        report.notes.extend(assess_one(startup, thesis, evidence, enrich=enrich))
        repo.save_startup(startup)
        report.ingested += 1
        _tally(report, startup)
    return report


def ingest(
    result: IngestionResult,
    repo: Repository,
    thesis: InvestmentThesis,
    evidence: EvidenceManager,
    *,
    dataset: Dataset = Dataset.REAL,
    enrich: bool = True,
) -> PipelineReport:
    """Take an adapter's output all the way to scored, persisted companies."""
    report = PipelineReport(
        ingested=result.rows_seen,
        warnings=list(result.warnings),
        errors=list(result.errors),
    )
    if not result.startups:
        return report

    # 1. Deduplicate within the incoming batch.
    incoming, dedup_report = deduplicate(result.startups)
    report.merged += dedup_report.merged_count
    report.warnings.extend(dedup_report.messages)

    # Evidence must follow its company when records were merged.
    surviving_ids = {s.id for s in incoming}
    id_remap: dict[str, str] = {}
    for startup in incoming:
        for merged in startup.raw_record.get("merged_from", []) or []:
            id_remap[merged["id"]] = startup.id
    for ev in result.evidence:
        if ev.startup_id not in surviving_ids:
            ev.startup_id = id_remap.get(ev.startup_id, ev.startup_id)
    evidence.add_many([ev for ev in result.evidence if ev.startup_id in surviving_ids or True])

    # 2. Merge against what is already stored (same dataset only).
    existing = repo.list_startups(dataset)
    for startup in incoming:
        startup.dataset = dataset
        match = find_existing(startup, existing)
        if match is not None:
            for ev in evidence.for_startup(startup.id):
                ev.startup_id = match.id
            merged = merge_pair(match, startup)
            report.notes.extend(assess_one(merged, thesis, evidence, enrich=enrich))
            repo.save_startup(merged)
            repo.save_evidence_many(evidence.for_startup(merged.id))
            report.merged += 1
            _tally(report, merged)
            continue

        report.notes.extend(assess_one(startup, thesis, evidence, enrich=enrich))
        repo.save_startup(startup)
        repo.save_evidence_many(evidence.for_startup(startup.id))
        existing.append(startup)
        report.added += 1
        _tally(report, startup)

    return report


def _tally(report: PipelineReport, startup: Startup) -> None:
    status = startup.eligibility_status.value
    if status == "ELIGIBLE":
        report.eligible += 1
    elif status == "NEEDS_REVIEW":
        report.needs_review += 1
    elif status == "INELIGIBLE":
        report.ineligible += 1


def load_workspace(repo: Repository, dataset: Dataset) -> tuple[list[Startup], EvidenceManager]:
    """Rehydrate companies and their evidence from the database."""
    startups = repo.list_startups(dataset)
    manager = EvidenceManager()
    for startup in startups:
        manager.add_many(repo.list_evidence(startup.id))
    return startups, manager


def ranked_candidates(startups: list[Startup]) -> list[Startup]:
    return rank(startups)


def shortlist_candidates(startups: list[Startup]) -> list[Startup]:
    return [s for s in startups if s.shortlisted]
