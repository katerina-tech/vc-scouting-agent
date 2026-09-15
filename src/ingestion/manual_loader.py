"""Manual company entry and URL-based entry.

``ManualEntryAdapter`` turns the Streamlit form into a Startup. ``URLSourceAdapter``
takes a company's own homepage URL and creates a *skeleton* record — it never
invents a sector, funding figure or founder list. Everything it reads from the
page (title, meta description) is recorded as INFERRED, not fact.
"""

from __future__ import annotations

import re
from typing import Any

from ..models.enums import Dataset, SourceType, VerificationStatus
from ..models.startup import Startup
from ..normalization.company_normalizer import (
    clean_display_name,
    extract_domain,
    normalize_company_name,
    normalize_url,
)
from .csv_loader import row_to_startup
from .source_adapter import IngestionResult, SourceAdapter


class ManualEntryAdapter(SourceAdapter):
    """The investor typing a company in by hand."""

    name = "manual"
    label = "Manual entry"
    source_type = SourceType.USER_INPUT

    def fetch(self, *, fields: dict[str, Any] | None = None,
              dataset: Dataset = Dataset.REAL, **_: Any) -> IngestionResult:
        result = IngestionResult()
        if not fields or not clean_display_name(fields.get("company_name")):
            result.errors.append("A company name is required.")
            return result

        result.rows_seen = 1
        startup, evidence, warnings = row_to_startup(
            dict(fields), dataset=dataset, adapter_name=self.name
        )
        result.warnings.extend(warnings)
        if startup is None:
            result.errors.append("Could not create a company from the supplied fields.")
            return result

        result.startups.append(startup)
        result.evidence.extend(evidence)
        result.warnings.append(
            f"{startup.company_name} was entered manually. Manual entries start as "
            "UNVERIFIED — add source URLs on the Company Research tab to verify them."
        )
        return result


class URLSourceAdapter(SourceAdapter):
    """Create a company from its own website URL.

    Fetching is optional and off by default (``ENRICHMENT_FETCH_ENABLED``). When
    disabled — or when the fetch fails — a skeleton record is still created so
    the investor can fill it in by hand. No third-party database is ever scraped.
    """

    name = "url"
    label = "Company URL"
    source_type = SourceType.COMPANY_WEBSITE

    def fetch(self, *, url: str | None = None, company_name: str | None = None,
              dataset: Dataset = Dataset.REAL, **_: Any) -> IngestionResult:
        from ..enrichment.company_enrichment import fetch_homepage_signals

        result = IngestionResult()
        normalized = normalize_url(url)
        if not normalized:
            result.errors.append(f"'{url}' is not a usable URL.")
            return result

        domain = extract_domain(normalized)
        result.rows_seen = 1

        name = clean_display_name(company_name) or _name_from_domain(domain)
        startup = Startup(
            company_name=name,
            normalized_name=normalize_company_name(name),
            website=normalized,
            domain=domain,
            dataset=dataset,
            source_adapter=self.name,
            source_urls=[normalized],
            raw_record={"input_url": url},
        )

        signals = fetch_homepage_signals(normalized)
        result.warnings.extend(signals.warnings)

        if signals.title and not company_name:
            startup.company_name = clean_display_name(signals.title.split("|")[0].split("–")[0])[:80] or name
            startup.normalized_name = normalize_company_name(startup.company_name)
        if signals.description:
            startup.product_summary = signals.description
        if signals.is_reachable is not None:
            startup.is_active = signals.is_reachable

        from ..models.evidence import Evidence

        result.evidence.append(
            Evidence(
                startup_id=startup.id, field_name="website", value=normalized,
                source_url=normalized, source_title="Company website",
                source_type=SourceType.COMPANY_WEBSITE,
                verification_status=VerificationStatus.VERIFIED,
                evidence_note="URL supplied by the investor.", added_by=self.name,
            )
        )
        for field_name, value, note in signals.evidence_tuples():
            result.evidence.append(
                Evidence(
                    startup_id=startup.id, field_name=field_name, value=value,
                    source_url=normalized, source_title="Company homepage",
                    source_type=SourceType.COMPANY_WEBSITE,
                    verification_status=VerificationStatus.INFERRED,
                    evidence_note=note, added_by=self.name,
                )
            )

        result.startups.append(startup)
        result.warnings.append(
            f"Created a skeleton record for {startup.company_name}. Sector, stage, funding "
            "and founders are deliberately empty — the app will not guess them."
        )
        return result


class BulkListAdapter(SourceAdapter):
    """Paste a sourcing list and get one skeleton record per line.

    This is the fastest honest route from "I found twenty interesting companies
    on EU-Startups this morning" to a structured research queue. Each line may be
    a URL, a company name, or ``Name, https://url`` in either order. Nothing is
    inferred beyond what the line literally says — every record arrives empty and
    UNVERIFIED, ready for the investor to research field by field.
    """

    name = "bulk"
    label = "Bulk list"
    source_type = SourceType.USER_INPUT

    def fetch(self, *, text: str | None = None, dataset: Dataset = Dataset.REAL,
              **_: Any) -> IngestionResult:
        result = IngestionResult()
        if not text or not text.strip():
            result.errors.append("Paste at least one company name or URL.")
            return result

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        result.rows_seen = len(lines)

        from ..models.evidence import Evidence

        for line in lines:
            company_name, url = _split_line(line)
            if not company_name and not url:
                continue

            normalized = normalize_url(url) if url else None
            domain = extract_domain(normalized) if normalized else None
            display = company_name or _name_from_domain(domain)

            startup = Startup(
                company_name=display,
                normalized_name=normalize_company_name(display),
                website=normalized,
                domain=domain,
                dataset=dataset,
                source_adapter=self.name,
                source_urls=[normalized] if normalized else [],
                raw_record={"input_line": line},
            )
            result.startups.append(startup)

            if normalized:
                result.evidence.append(
                    Evidence(
                        startup_id=startup.id, field_name="website", value=normalized,
                        source_url=normalized, source_title="Company website",
                        source_type=SourceType.COMPANY_WEBSITE,
                        verification_status=VerificationStatus.VERIFIED,
                        evidence_note="URL supplied by the investor in a sourcing list.",
                        added_by=self.name,
                    )
                )

        if not result.startups:
            result.errors.append("Nothing usable was found in that list.")
            return result

        result.warnings.append(
            f"Created {len(result.startups)} skeleton record(s). Country, stage, funding "
            "and founders are deliberately empty — fill them in on Company Research, "
            "attaching a source to each, and they will move out of Needs review."
        )
        return result


_URL_IN_LINE = re.compile(r"(https?://\S+|(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:/\S*)?)", re.IGNORECASE)


def _split_line(line: str) -> tuple[str, str]:
    """Split ``Acme GmbH, https://acme.io`` (in either order) into name and URL."""
    cleaned = line.strip().strip("-•*\t ")
    match = _URL_IN_LINE.search(cleaned)
    url = match.group(0) if match else ""
    name = cleaned.replace(url, "") if url else cleaned
    name = clean_display_name(name.strip(" ,;|\t-–—"))
    if url and not normalize_url(url):
        # It looked like a domain but is not one; treat the whole line as a name.
        return clean_display_name(cleaned), ""
    return name, url


def _name_from_domain(domain: str | None) -> str:
    if not domain:
        return "Unnamed company"
    root = domain.split(".")[0].replace("-", " ")
    return root.title() or "Unnamed company"


#: The fields the manual-entry form exposes, in display order.
MANUAL_FORM_FIELDS: list[tuple[str, str, str]] = [
    ("company_name", "Company name *", "text"),
    ("website", "Website", "text"),
    ("hq_country", "HQ country", "text"),
    ("city", "City", "text"),
    ("founded_year", "Founded year", "text"),
    ("sector", "Sector", "text"),
    ("subsector", "Subsector", "text"),
    ("stage", "Stage", "stage"),
    ("total_funding_eur", "Total funding (e.g. €1.8M, 1800000, unknown)", "text"),
    ("funding_source_url", "Funding source URL (makes the figure verifiable)", "text"),
    ("last_round_eur", "Last round amount", "text"),
    ("last_round_date", "Last round date (YYYY-MM-DD)", "text"),
    ("investors", "Investors (semicolon-separated)", "text"),
    ("founders", "Founders (semicolon-separated)", "text"),
    ("founder_background", "Founder background", "textarea"),
    ("product_summary", "What the company does", "textarea"),
    ("business_model", "Business model", "text"),
    ("customers", "Customers (semicolon-separated)", "text"),
    ("traction_signals", "Traction signals (semicolon-separated)", "textarea"),
    ("technology", "Technology", "textarea"),
    ("technical_moat", "Technical moat / defensibility", "textarea"),
    ("competitors", "Competitors (semicolon-separated)", "text"),
    ("market_size_signal", "Market size signal", "textarea"),
    ("impact_signal", "Impact signal", "textarea"),
    ("why_now_signal", "Why now", "textarea"),
    ("source_urls", "Source URLs (semicolon-separated)", "textarea"),
    ("notes", "Notes", "textarea"),
]
