"""The import wizard: reading real-world files and mapping their columns.

These tests exist because every real source spells its columns differently.
The point of the wizard is that the application never has to guess — so what is
tested here is that an explicit mapping always wins, and that an unmapped
column is ignored rather than silently interpreted.
"""

from __future__ import annotations

import io

import pandas as pd
import pytest

from src.ingestion.csv_loader import (
    CSVSourceAdapter,
    apply_mapping,
    read_table,
    suggest_mapping,
)
from src.models.enums import Dataset, SourceTier, SourceType, VerificationStatus

# An export in the shape a European source actually produces: semicolon
# separated, unfamiliar column names, a comma decimal, an accented country.
EPO_STYLE = (
    "Applicant name;Country of establishment;Year of foundation;Technology field;Web page\n"
    "Sölar Energy GmbH;Germany;2021;Clean energy;https://solar-energy.example\n"
    "Bio Diagnostics BV;Netherlands;2022;Medical technology;https://biodx.example\n"
)

EIC_STYLE = (
    "Beneficiary,Country,Grant awarded,Project,Link\n"
    "Thermal Systems SL,Spain,\"€2.4M\",HeatLoop,https://eic.example/thermal\n"
)


# --------------------------------------------------------------------- reading
def test_a_semicolon_separated_file_is_read_without_configuration():
    frame, error = read_table(content=EPO_STYLE, filename="epo.csv")
    assert error == ""
    assert len(frame) == 2
    assert "Applicant name" in frame.columns


def test_a_comma_separated_file_is_also_read():
    frame, error = read_table(content=EIC_STYLE, filename="eic.csv")
    assert error == ""
    assert len(frame) == 1


def test_latin1_encoded_bytes_are_decoded():
    frame, error = read_table(
        content=EPO_STYLE.encode("latin-1"), filename="epo.csv"
    )
    assert error == ""
    assert len(frame) == 2


def test_an_excel_file_is_read():
    buffer = io.BytesIO()
    pd.DataFrame(
        {"Applicant name": ["Acme GmbH"], "Country of establishment": ["Germany"]}
    ).to_excel(buffer, index=False)
    frame, error = read_table(content=buffer.getvalue(), filename="export.xlsx")
    assert error == ""
    assert frame.iloc[0]["Applicant name"] == "Acme GmbH"


def test_an_unreadable_file_returns_an_error_not_an_exception():
    frame, error = read_table(content=b"\x00\x01\x02binary nonsense", filename="x.csv")
    assert frame is None or frame.empty or error
    frame, error = read_table()
    assert frame is None and error


# -------------------------------------------------------------------- mapping
def test_recognisable_columns_are_suggested():
    suggestion = suggest_mapping(["Company", "Country", "Total Funding", "Website"])
    assert suggestion["company_name"] == "Company"
    assert suggestion["hq_country"] == "Country"
    assert suggestion["total_funding_eur"] == "Total Funding"


def test_unrecognisable_columns_are_not_guessed():
    """An EPO export has no column the alias table knows — that is the point."""
    suggestion = suggest_mapping(
        ["Applicant name", "Country of establishment", "Year of foundation"]
    )
    assert "company_name" not in suggestion


def test_apply_mapping_keeps_only_mapped_columns():
    frame, _ = read_table(content=EPO_STYLE, filename="epo.csv")
    mapped = apply_mapping(
        frame,
        {"company_name": "Applicant name", "hq_country": "Country of establishment"},
    )
    assert list(mapped.columns) == ["company_name", "hq_country"]
    assert "Technology field" not in mapped.columns


# ------------------------------------------------------------------- importing
def test_an_explicit_mapping_imports_an_otherwise_unreadable_export():
    result = CSVSourceAdapter().fetch(
        content=EPO_STYLE,
        filename="epo.csv",
        dataset=Dataset.REAL,
        mapping={
            "company_name": "Applicant name",
            "hq_country": "Country of establishment",
            "founded_year": "Year of foundation",
            "sector": "Technology field",
            "website": "Web page",
        },
        source_type=SourceType.REGULATORY_RECORD,
    )

    assert result.ok, result.errors
    assert len(result.startups) == 2

    first = next(s for s in result.startups if "Sol" in s.normalized_name or "sol" in s.normalized_name)
    assert first.hq_country == "Germany"
    assert first.founded_year == 2021
    assert first.website == "https://solar-energy.example"


def test_the_same_file_without_a_mapping_is_refused_with_a_clear_message():
    result = CSVSourceAdapter().fetch(content=EPO_STYLE, filename="epo.csv")
    assert not result.ok
    assert "column-mapping" in result.errors[0]


def test_importing_without_a_company_name_mapping_is_refused():
    result = CSVSourceAdapter().fetch(
        content=EPO_STYLE, filename="epo.csv",
        mapping={"hq_country": "Country of establishment"},
    )
    assert not result.ok
    assert "Company name" in result.errors[0]


def test_the_declared_source_type_sets_the_evidence_tier():
    """An official register must import at a higher tier than a directory."""
    official = CSVSourceAdapter().fetch(
        content=EIC_STYLE, filename="eic.csv",
        mapping={"company_name": "Beneficiary", "hq_country": "Country",
                 "source_urls": "Link"},
        source_type=SourceType.REGULATORY_RECORD,
    )
    directory = CSVSourceAdapter().fetch(
        content=EIC_STYLE, filename="eic.csv",
        mapping={"company_name": "Beneficiary", "hq_country": "Country",
                 "source_urls": "Link"},
        source_type=SourceType.STARTUP_DIRECTORY,
    )

    official_country = next(
        e for e in official.evidence if e.field_name == "hq_country"
    )
    directory_country = next(
        e for e in directory.evidence if e.field_name == "hq_country"
    )

    assert official_country.source_tier == SourceTier.TIER_1
    assert directory_country.source_tier == SourceTier.TIER_3
    assert official_country.confidence > directory_country.confidence


def test_funding_imported_without_a_source_url_is_still_unverified():
    """The wizard cannot be used to launder an unsourced number into a fact."""
    result = CSVSourceAdapter().fetch(
        content=EIC_STYLE, filename="eic.csv",
        mapping={"company_name": "Beneficiary", "total_funding_eur": "Grant awarded"},
        source_type=SourceType.REGULATORY_RECORD,
    )
    startup = result.startups[0]
    assert startup.total_funding_eur == pytest.approx(2_400_000)

    funding_evidence = [e for e in result.evidence if e.field_name == "total_funding_eur"]
    assert funding_evidence
    assert all(
        e.verification_status != VerificationStatus.VERIFIED for e in funding_evidence
    )


def test_an_unmapped_column_never_reaches_the_record():
    result = CSVSourceAdapter().fetch(
        content=EPO_STYLE, filename="epo.csv",
        mapping={"company_name": "Applicant name"},
        source_type=SourceType.REGULATORY_RECORD,
    )
    startup = result.startups[0]
    assert startup.hq_country is None
    assert startup.sector is None
    assert startup.founded_year is None
