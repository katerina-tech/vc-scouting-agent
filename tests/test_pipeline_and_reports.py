"""End-to-end: ingestion, persistence, memo and Loom generation — all offline."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion.csv_loader import CSVSourceAdapter, normalize_headers
from src.ingestion.manual_loader import ManualEntryAdapter, URLSourceAdapter
from src.ingestion.source_adapter import PLANNED_ADAPTERS, adapter_registry
from src.llm.client import NullLLMClient, get_llm_client, parse_json
from src.llm.investment_analyst import offline_analyst
from src.models.enums import Dataset, EligibilityStatus, Recommendation, VerificationStatus
from src.pipeline import ingest
from src.reports.investment_memo import SECTION_ORDER, decide_recommendation, generate_memo
from src.reports.loom_script import STRUCTURE, count_words, generate_loom_script
from src.research.evidence_manager import EvidenceManager
from src.storage.repository import Repository
from tests.conftest import make_startup

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample_startups.csv"

CSV_WITH_SOURCE = """company_name,hq_country,stage,total_funding_eur,funding_source_url,sector,product_summary,is_active,founded_year
Alpha Climate GmbH,Germany,Seed,€1.8M,https://press.example/alpha,Climate,Carbon accounting software,true,2022
"""

CSV_WITHOUT_SOURCE = """company_name,hq_country,stage,total_funding_eur,sector,product_summary,is_active,founded_year
Beta Climate GmbH,Germany,Seed,€1.8M,Climate,Carbon accounting software,true,2022
"""


# ------------------------------------------------------------------- CSV
def test_header_aliases_are_matched_flexibly():
    mapping = normalize_headers(["Company", "HQ", "Total Funding", "Website", "nonsense"])
    assert mapping["Company"] == "company_name"
    assert mapping["HQ"] == "hq_country"
    assert mapping["Total Funding"] == "total_funding_eur"
    assert "nonsense" not in mapping


def test_a_csv_without_a_name_column_is_rejected_clearly():
    result = CSVSourceAdapter().fetch(content="foo,bar\n1,2\n")
    assert not result.ok
    assert "company-name column" in result.errors[0]


def test_a_funding_figure_with_a_source_url_becomes_verified(repo, evidence, thesis):
    result = CSVSourceAdapter().fetch(content=CSV_WITH_SOURCE, dataset=Dataset.DEMO)
    ingest(result, repo, thesis, evidence, dataset=Dataset.DEMO, enrich=False)
    startup = repo.list_startups(Dataset.DEMO)[0]
    assert startup.funding_status == VerificationStatus.VERIFIED
    assert startup.eligibility_status == EligibilityStatus.ELIGIBLE


def test_the_same_figure_without_a_source_url_does_not(repo, evidence, thesis):
    result = CSVSourceAdapter().fetch(content=CSV_WITHOUT_SOURCE, dataset=Dataset.DEMO)
    ingest(result, repo, thesis, evidence, dataset=Dataset.DEMO, enrich=False)
    startup = repo.list_startups(Dataset.DEMO)[0]
    assert startup.funding_status != VerificationStatus.VERIFIED
    assert startup.eligibility_status == EligibilityStatus.NEEDS_REVIEW


# ------------------------------------------------------------ demo dataset
@pytest.mark.skipif(not SAMPLE.exists(), reason="sample CSV missing")
def test_the_demo_dataset_exercises_every_eligibility_outcome(repo, evidence, thesis):
    result = CSVSourceAdapter().fetch(path=str(SAMPLE), dataset=Dataset.DEMO)
    assert result.ok
    report = ingest(result, repo, thesis, evidence, dataset=Dataset.DEMO, enrich=False)

    # Deliberately small: the demo set exists only to prove the pipeline works
    # end to end. Real companies are the point of the product, so the fixture
    # is kept to the four rows needed to hit every eligibility outcome.
    assert report.added >= 4
    assert report.eligible >= 1
    assert report.needs_review >= 1
    assert report.ineligible >= 1


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample CSV missing")
def test_every_demo_company_is_flagged_as_demo_data(repo, evidence, thesis):
    result = CSVSourceAdapter().fetch(path=str(SAMPLE), dataset=Dataset.DEMO)
    ingest(result, repo, thesis, evidence, dataset=Dataset.DEMO, enrich=False)
    stored = repo.list_startups(Dataset.DEMO)
    assert stored
    assert all(s.is_demo for s in stored)
    assert all(s.company_name.startswith("DEMO") for s in stored)
    assert repo.count(Dataset.REAL) == 0, "demo data must never leak into the real dataset"


# ------------------------------------------------------------- persistence
def test_a_company_round_trips_through_sqlite_without_loss(repo, thesis):
    from src.scoring.score_engine import apply_score

    original = apply_score(make_startup(), thesis)
    repo.save_startup(original)
    restored = repo.get_startup(original.id)

    assert restored.company_name == original.company_name
    assert restored.total_funding_eur == original.total_funding_eur
    assert restored.score_total == original.score_total
    assert len(restored.score_breakdown.criteria) == len(original.score_breakdown.criteria)


def test_the_shortlist_survives_a_reload(repo):
    startup = make_startup()
    repo.save_startup(startup)
    repo.add_to_shortlist(startup.id, "Strong founder-market fit")
    assert [s.id for s in repo.list_shortlist()] == [startup.id]
    assert repo.get_startup(startup.id).shortlisted is True

    repo.remove_from_shortlist(startup.id)
    assert repo.list_shortlist() == []


def test_overrides_are_persisted(repo):
    startup = make_startup()
    repo.save_startup(startup)
    startup.record_override("city", "Munich", reason="Checked the imprint.")
    repo.save_override(startup.id, startup.human_overrides[-1])
    stored = repo.list_overrides(startup.id)
    assert stored[0]["field_name"] == "city"
    assert "imprint" in stored[0]["reason"]


# -------------------------------------------------------------- adapters
def test_paid_adapters_report_themselves_unavailable_rather_than_faking_data():
    for adapter in PLANNED_ADAPTERS:
        if adapter.is_available():
            continue
        result = adapter.fetch()
        assert result.startups == [], "a stub adapter must never return invented companies"
        assert result.errors
        assert adapter.env_var in result.errors[0]


def test_the_registry_exposes_the_three_live_inputs():
    registry = adapter_registry()
    assert {"csv", "manual", "url"} <= set(registry)
    assert registry["csv"].is_available()


def test_manual_entry_requires_a_company_name():
    assert not ManualEntryAdapter().fetch(fields={"website": "https://x.example"}).ok


def test_a_url_record_is_a_skeleton_not_a_guess():
    result = URLSourceAdapter().fetch(url="https://example-startup.example")
    assert result.ok
    startup = result.startups[0]
    assert startup.total_funding_eur is None
    assert startup.stage.value == "UNKNOWN"
    assert startup.founders == []


# ------------------------------------------------------------------- LLM
def test_the_app_runs_without_an_llm():
    client = get_llm_client.__wrapped__() if hasattr(get_llm_client, "__wrapped__") else NullLLMClient()
    assert client.available is False
    response = client.complete("system", "user")
    assert response.ok is False
    assert response.error


def test_json_parsing_survives_code_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": 1} hope that helps') == {"a": 1}
    assert parse_json("not json at all") is None


def test_the_offline_analyst_still_produces_thesis_fit(thesis):
    analyst = offline_analyst()
    result = analyst.thesis_fit(make_startup(), thesis)
    assert result.available is False  # no LLM was used
    assert result.data.supporting_points  # but there is still an answer


# ------------------------------------------------------------------ memo
def test_a_memo_is_complete_without_an_llm(thesis):
    from src.filters.eligibility import apply_eligibility
    from src.research.red_flags import apply_red_flags
    from src.scoring.score_engine import apply_score

    startup = apply_red_flags(apply_score(apply_eligibility(make_startup(), thesis), thesis), thesis)
    memo = generate_memo(startup, thesis, EvidenceManager(), offline_analyst())

    assert memo.llm_used is False
    for key, _ in SECTION_ORDER:
        assert key in memo.sections
    assert memo.questions_for_founders
    assert "Investment memo" in memo.to_markdown()


def test_no_automatic_invest_recommendation_exists():
    assert not hasattr(Recommendation, "INVEST")
    assert {r.value for r in Recommendation} == {"PASS", "WATCH", "INVESTIGATE"}


def test_an_ineligible_company_is_always_a_pass(thesis):
    from src.filters.eligibility import apply_eligibility
    from src.scoring.score_engine import apply_score

    startup = apply_score(
        apply_eligibility(make_startup(hq_country="United States"), thesis), thesis
    )
    recommendation, reason = decide_recommendation(startup)
    assert recommendation == Recommendation.PASS_
    assert "hard eligibility" in reason


def test_a_high_score_on_thin_evidence_cannot_reach_investigate(thesis):
    from src.filters.eligibility import apply_eligibility
    from src.scoring.score_engine import apply_score

    startup = apply_eligibility(make_startup(), thesis)
    apply_score(startup, thesis)
    startup.score_total = 95.0
    for criterion in startup.score_breakdown.criteria:
        criterion.confidence = 0.1

    recommendation, reason = decide_recommendation(startup)
    assert recommendation == Recommendation.WATCH
    assert "confidence" in reason.lower()


# ------------------------------------------------------------------ Loom
def test_the_loom_script_covers_the_seven_beats_and_fits_the_window(thesis):
    from src.filters.eligibility import apply_eligibility
    from src.scoring.score_engine import apply_score

    startup = apply_score(apply_eligibility(make_startup(), thesis), thesis)
    pitch = generate_loom_script(startup, thesis, EvidenceManager(), offline_analyst())

    assert len(STRUCTURE) == 7
    assert 60 <= pitch.word_count <= 150
    assert 25 <= pitch.estimated_seconds <= 65
    assert count_words(pitch.script) == pitch.word_count
    assert startup.company_name in pitch.script


def test_a_thin_company_still_produces_a_script_but_warns(thesis):
    startup = make_startup(
        product_summary=None, market_size_signal=None, impact_signal=None,
        why_now_signal=None, technical_moat=None, technology=None,
        customers=[], traction_signals=[],
    )
    pitch = generate_loom_script(startup, thesis, EvidenceManager(), offline_analyst())
    assert pitch.script
    assert pitch.warnings, "a thin script must tell the user why it is thin"


def test_acronyms_survive_script_generation(thesis):
    startup = make_startup(why_now_signal="CSRD comes into force from 2025")
    pitch = generate_loom_script(startup, thesis, EvidenceManager(), offline_analyst())
    assert "CSRD" in pitch.script
    assert "csrd" not in pitch.script
