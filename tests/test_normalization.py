"""Normalization: currency, stages, geography, names, dates."""

from __future__ import annotations

import pytest

from src.models.enums import Stage
from src.normalization.company_normalizer import (
    FX_RATES_PER_EUR,
    extract_domain,
    infer_themes,
    is_european,
    normalize_company_name,
    normalize_country,
    normalize_date,
    normalize_funding,
    normalize_stage,
    normalize_url,
    normalize_year,
    parse_money,
    split_list,
    to_eur,
)


# --------------------------------------------------------------- currency
@pytest.mark.parametrize(
    "raw, expected_amount, expected_currency",
    [
        ("€1.8M", 1_800_000, "EUR"),
        ("1,800,000 EUR", 1_800_000, "EUR"),
        ("1.800.000", 1_800_000, "EUR"),
        ("1 800 000", 1_800_000, "EUR"),
        ("750k", 750_000, "EUR"),
        ("$2m", 2_000_000, "USD"),
        ("1.5m GBP", 1_500_000, "GBP"),
        ("£900k", 900_000, "GBP"),
        ("2.5 million CHF", 2_500_000, "CHF"),
        (2_500_000, 2_500_000, "EUR"),
    ],
)
def test_parse_money_handles_real_world_spellings(raw, expected_amount, expected_currency):
    amount, currency, _ = parse_money(raw)
    assert amount == pytest.approx(expected_amount)
    assert currency == expected_currency


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Regression: a plain integer with no separators used to be truncated to
        # its first three digits, so €1,400,000 was silently read as €140 and a
        # company sailed under a €3M ceiling it should never have cleared.
        ("1400000", 1_400_000),
        ("€1800000", 1_800_000),
        ("2200000", 2_200_000),
        ("345000", 345_000),
        ("1000", 1_000),
        ("750", 750),
        ("99", 99),
    ],
)
def test_plain_integers_are_not_truncated(raw, expected):
    amount, _, _ = parse_money(raw)
    assert amount == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["unknown", "undisclosed", "n/a", "", None, "-", "?"])
def test_unparseable_funding_returns_none_never_a_guess(raw):
    amount, _, _ = parse_money(raw)
    assert amount is None


def test_currency_conversion_to_eur_uses_the_documented_rate():
    converted, note = to_eur(2_000_000, "USD")
    assert converted == pytest.approx(2_000_000 / FX_RATES_PER_EUR["USD"], rel=1e-6)
    assert "USD/EUR" in note


def test_eur_values_are_not_converted_and_carry_no_note():
    converted, note = to_eur(1_000_000, "EUR")
    assert converted == 1_000_000
    assert note is None


def test_unknown_currency_is_refused_rather_than_assumed():
    converted, note = to_eur(1_000, "XYZ")
    assert converted is None
    assert "Unknown currency" in note


def test_normalize_funding_keeps_the_raw_value():
    result = normalize_funding("$2m")
    assert result["raw"] == "$2m"
    assert result["currency"] == "USD"
    assert result["amount_eur"] == pytest.approx(1_851_851.85, rel=1e-4)


# ------------------------------------------------------------------ stage
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Pre-Seed", Stage.PRE_SEED), ("preseed", Stage.PRE_SEED), ("angel", Stage.PRE_SEED),
        ("Seed", Stage.SEED), ("seed round", Stage.SEED), ("Seed Extension", Stage.SEED),
        ("Series A", Stage.SERIES_A), ("Series B", Stage.SERIES_B_PLUS),
        ("growth", Stage.SERIES_B_PLUS), ("bootstrapped", Stage.BOOTSTRAPPED),
        ("grant", Stage.GRANT_FUNDED),
    ],
)
def test_stage_normalization(raw, expected):
    assert normalize_stage(raw) == expected


@pytest.mark.parametrize("raw", ["blah", "", None, "???", "whatever"])
def test_unrecognised_stage_becomes_unknown_not_a_guess(raw):
    assert normalize_stage(raw) == Stage.UNKNOWN


# -------------------------------------------------------------- geography
@pytest.mark.parametrize(
    "raw, expected",
    [("de", "Germany"), ("Deutschland", "Germany"), ("UK", "United Kingdom"),
     ("Great Britain", "United Kingdom"), ("españa", "Spain"), ("NL", "Netherlands")],
)
def test_country_aliases_resolve(raw, expected):
    assert normalize_country(raw) == expected


@pytest.mark.parametrize("country", ["Germany", "de", "UK", "Estonia", "Portugal", "Ukraine"])
def test_european_countries_are_recognised(country):
    assert is_european(country) is True


@pytest.mark.parametrize("country", ["United States", "USA", "Israel", "Singapore", "Canada"])
def test_non_european_countries_are_rejected(country):
    assert is_european(country) is False


@pytest.mark.parametrize("country", [None, "", "unknown", "n/a"])
def test_unknown_country_is_none_not_false(country):
    """None means 'we do not know', which must not be treated as 'not European'."""
    assert is_european(country) is None


# ------------------------------------------------------------------ names
def test_legal_suffixes_are_stripped_for_comparison():
    assert normalize_company_name("Acme GmbH") == "acme"
    assert normalize_company_name("Acme B.V.") == "acme"
    assert normalize_company_name("Acme Ltd") == "acme"
    assert normalize_company_name("Sölar Energy GmbH & Co. KG") == "solar energy"


def test_urls_and_domains_are_canonicalised():
    assert normalize_url("www.Acme.io") == "https://acme.io"
    assert extract_domain("https://WWW.Acme.io/about") == "acme.io"
    assert extract_domain("not a url at all") is None


# ------------------------------------------------------------------ dates
def test_date_formats():
    assert normalize_date("2024-03-15").isoformat() == "2024-03-15"
    assert normalize_date("15.03.2024").isoformat() == "2024-03-15"
    assert normalize_date("unknown") is None


def test_year_extraction_rejects_nonsense():
    assert normalize_year("founded 2021") == 2021
    assert normalize_year("1820") is None
    assert normalize_year("no year here") is None


# ----------------------------------------------------------------- themes
def test_theme_inference_is_conservative():
    assert infer_themes("Climate tech", "carbon accounting") == ["Climate"]
    assert "Health" in infer_themes("digital health diagnostics")
    assert infer_themes("quantum widgets for widget enthusiasts") == []
    assert infer_themes(None, "") == []


def test_list_splitting():
    assert split_list("a; b, c") == ["a", "b", "c"]
    assert split_list("unknown") == []
    assert split_list(None) == []
