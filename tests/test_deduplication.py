"""Duplicate detection and evidence-preserving merges."""

from __future__ import annotations

from src.models.enums import Dataset, Stage, VerificationStatus
from src.normalization.deduplication import dedup_key, deduplicate, find_existing, merge_pair
from tests.conftest import make_startup


def test_same_domain_different_spelling_is_one_company():
    a = make_startup(company_name="Acme GmbH", website="https://acme.io", domain="acme.io")
    b = make_startup(company_name="ACME", website="https://www.acme.io/", domain="acme.io")
    merged, report = deduplicate([a, b])
    assert len(merged) == 1
    assert report.merged_count == 1
    assert "domain" in report.groups[0].match_reason


def test_same_normalized_name_without_a_domain_is_one_company():
    a = make_startup(company_name="Acme GmbH", website=None, domain=None)
    b = make_startup(company_name="Acme Ltd", website=None, domain=None)
    merged, _ = deduplicate([a, b])
    assert len(merged) == 1


def test_different_companies_are_not_merged():
    a = make_startup(company_name="Acme GmbH", domain="acme.io")
    b = make_startup(company_name="Umbrella BV", domain="umbrella.nl")
    merged, report = deduplicate([a, b])
    assert len(merged) == 2
    assert report.merged_count == 0


def test_demo_and_real_records_are_never_merged():
    demo = make_startup(company_name="Acme GmbH", domain="acme.io", dataset=Dataset.DEMO)
    real = make_startup(company_name="Acme GmbH", domain="acme.io", dataset=Dataset.REAL)
    merged, _ = deduplicate([demo, real])
    assert len(merged) == 2


def test_dedup_key_prefers_domain_over_name():
    key, reason = dedup_key(make_startup(domain="acme.io"))
    assert key == "domain:acme.io"
    assert "domain" in reason

    key, reason = dedup_key(make_startup(website=None, domain=None, company_name="Acme GmbH"))
    assert key == "name:acme"


# ------------------------------------------------------------------- merge
def test_merging_fills_gaps_without_overwriting_good_data():
    rich = make_startup(company_name="Acme", city="Berlin", technology="Existing tech")
    sparse = make_startup(company_name="Acme", city=None, technology="Other tech",
                          impact_signal="new impact signal")
    sparse.market_size_signal = None

    merged = merge_pair(rich, sparse)
    assert merged.city == "Berlin"
    assert merged.technology == "Existing tech"  # not overwritten


def test_merging_unions_list_fields_without_duplicates():
    a = make_startup(investors=["Alpha VC"], customers=["Acme Works"])
    b = make_startup(investors=["Beta VC", "Alpha VC"], customers=["Gamma AG", "acme works"])
    merged = merge_pair(a, b)
    assert sorted(merged.investors) == ["Alpha VC", "Beta VC"]
    # "acme works" is the same customer as "Acme Works" and must not be duplicated.
    assert sorted(merged.customers) == ["Acme Works", "Gamma AG"]


def test_the_better_verified_funding_figure_wins():
    weak = make_startup(total_funding_eur=900_000.0, funding_status=VerificationStatus.UNVERIFIED)
    strong = make_startup(total_funding_eur=1_800_000.0, funding_status=VerificationStatus.VERIFIED)
    merged = merge_pair(weak, strong)
    assert merged.total_funding_eur == 1_800_000.0
    assert merged.funding_status == VerificationStatus.VERIFIED


def test_a_known_stage_fills_an_unknown_one():
    unknown = make_startup(stage=Stage.UNKNOWN)
    known = make_startup(stage=Stage.PRE_SEED)
    assert merge_pair(unknown, known).stage == Stage.PRE_SEED


def test_merging_records_where_the_data_came_from():
    a = make_startup(company_name="Acme")
    b = make_startup(company_name="Acme", source_adapter="csv")
    merged = merge_pair(a, b)
    assert merged.raw_record["merged_from"][0]["company_name"] == "Acme"


def test_find_existing_matches_across_a_stored_set():
    stored = [make_startup(company_name="Acme GmbH", domain="acme.io")]
    incoming = make_startup(company_name="Acme Limited", domain="acme.io")
    assert find_existing(incoming, stored) is stored[0]

    unrelated = make_startup(company_name="Umbrella", domain="umbrella.nl")
    assert find_existing(unrelated, stored) is None
