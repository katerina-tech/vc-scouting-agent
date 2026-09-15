"""Shared fixtures. No test in this suite needs an API key or a network connection."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models.enums import Dataset, SourceType, Stage, VerificationStatus  # noqa: E402
from src.models.evidence import Evidence  # noqa: E402
from src.models.startup import Startup  # noqa: E402
from src.models.thesis import InvestmentThesis  # noqa: E402
from src.research.evidence_manager import EvidenceManager  # noqa: E402
from src.storage.repository import Repository  # noqa: E402


@pytest.fixture
def thesis() -> InvestmentThesis:
    return InvestmentThesis()


@pytest.fixture
def repo() -> Repository:
    repository = Repository(":memory:")
    yield repository
    repository.close()


@pytest.fixture
def evidence() -> EvidenceManager:
    return EvidenceManager()


def make_startup(**overrides) -> Startup:
    """A complete, eligible, well-evidenced company. Override to break one thing."""
    defaults = dict(
        company_name="Testco GmbH",
        normalized_name="testco",
        website="https://testco.example",
        domain="testco.example",
        dataset=Dataset.DEMO,
        hq_country="Germany",
        city="Berlin",
        founded_year=2022,
        sector="Climate",
        themes=["Climate"],
        stage=Stage.SEED,
        is_active=True,
        total_funding_eur=1_800_000.0,
        total_funding_raw="€1.8M",
        funding_status=VerificationStatus.VERIFIED,
        founders=["Anna Klein"],
        founder_background="PhD in atmospheric science; 10 years of experience; previously at Siemens",
        product_summary="Carbon accounting software for manufacturers",
        business_model="SaaS subscription",
        customers=["Acme Works", "Beta GmbH"],
        traction_signals=["2 paying customers", "multi-year contract signed"],
        technology="Proprietary emissions dataset",
        technical_moat="proprietary dataset; deep integration with SAP",
        competitors=["CompetitorA"],
        market_size_signal="€12bn market for sustainability reporting",
        impact_signal="tonnes of CO2e avoided",
        why_now_signal="CSRD comes into force from 2025 with a reporting deadline",
        source_urls=["https://press.example/testco"],
    )
    defaults.update(overrides)
    if "normalized_name" not in overrides:
        from src.normalization.company_normalizer import normalize_company_name

        defaults["normalized_name"] = normalize_company_name(defaults["company_name"])
    return Startup(**defaults)


def verified_funding_evidence(startup: Startup, amount: float | None = None) -> Evidence:
    return Evidence(
        startup_id=startup.id,
        field_name="total_funding_eur",
        value=amount if amount is not None else startup.total_funding_eur,
        source_url="https://press.example/testco-seed",
        source_title="Seed round announcement",
        source_type=SourceType.FUNDING_ANNOUNCEMENT,
        verification_status=VerificationStatus.VERIFIED,
    )


@pytest.fixture
def startup() -> Startup:
    return make_startup()
