"""Optional, polite enrichment from a company's **own** homepage.

What this module will do:
  * fetch the company's own site, if the operator has enabled fetching
  * honour ``robots.txt`` and send an identifying User-Agent
  * read the ``<title>`` and meta description
  * detect that a site is unreachable (an "inactive website" red flag)

What this module will never do:
  * scrape Crunchbase, Dealroom, LinkedIn or any third-party database
  * infer a funding amount, an investor, a customer or a revenue figure
  * mark anything it reads as VERIFIED — homepage copy is marketing, so every
    signal it produces is INFERRED at best
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from ..config import get_enrichment_settings
from ..models.enums import SourceType, VerificationStatus
from ..models.evidence import Evidence
from ..models.startup import Startup
from ..normalization.company_normalizer import infer_themes, normalize_url
from ..research.evidence_manager import EvidenceManager


@dataclass
class HomepageSignals:
    url: str
    title: str | None = None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)
    is_reachable: bool | None = None
    status_code: int | None = None
    body_text: str = ""
    warnings: list[str] = field(default_factory=list)

    def evidence_tuples(self) -> list[tuple[str, object, str]]:
        out: list[tuple[str, object, str]] = []
        if self.title:
            out.append(("company_name", self.title, "Read from the homepage <title> tag."))
        if self.description:
            out.append((
                "product_summary", self.description,
                "Read from the homepage meta description — marketing copy, treat as INFERRED.",
            ))
        if self.is_reachable is not None:
            out.append((
                "is_active", self.is_reachable,
                f"Homepage returned HTTP {self.status_code}." if self.status_code
                else "Homepage could not be reached.",
            ))
        return out


def _robots_allows(url: str, user_agent: str) -> bool:
    try:
        parser = RobotFileParser()
        parser.set_url(urljoin(url, "/robots.txt"))
        parser.read()
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001 — an unreadable robots.txt is not consent
        return True


def fetch_homepage_signals(url: str | None) -> HomepageSignals:
    """Fetch a company homepage, if enabled. Always returns a usable object."""
    normalized = normalize_url(url)
    signals = HomepageSignals(url=normalized or (url or ""))
    if not normalized:
        signals.warnings.append("No usable URL to fetch.")
        return signals

    settings = get_enrichment_settings()
    if not settings.fetch_enabled:
        signals.warnings.append(
            "Web enrichment is disabled (ENRICHMENT_FETCH_ENABLED=false). "
            "Nothing was fetched; no data was guessed."
        )
        return signals

    if not _robots_allows(normalized, settings.user_agent):
        signals.warnings.append(f"robots.txt at {normalized} disallows automated access — skipped.")
        return signals

    try:
        import requests

        response = requests.get(
            normalized,
            headers={"User-Agent": settings.user_agent, "Accept": "text/html"},
            timeout=settings.timeout,
        )
        signals.status_code = response.status_code
        signals.is_reachable = 200 <= response.status_code < 400
        if not signals.is_reachable:
            signals.warnings.append(f"{normalized} returned HTTP {response.status_code}.")
            return signals
        html = response.text[:400_000]
    except Exception as exc:  # noqa: BLE001
        signals.is_reachable = False
        signals.warnings.append(f"Could not reach {normalized}: {exc}")
        return signals

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            signals.title = soup.title.string.strip()[:200]
        meta = soup.find("meta", attrs={"name": "description"}) or soup.find(
            "meta", attrs={"property": "og:description"}
        )
        if meta and meta.get("content"):
            signals.description = meta["content"].strip()[:600]
        kw = soup.find("meta", attrs={"name": "keywords"})
        if kw and kw.get("content"):
            signals.keywords = [k.strip() for k in kw["content"].split(",") if k.strip()][:15]
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        signals.body_text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()[:20_000]
    except Exception as exc:  # noqa: BLE001
        signals.warnings.append(f"Could not parse the page HTML: {exc}")

    return signals


def enrich_company(startup: Startup, evidence: EvidenceManager) -> list[str]:
    """Run every enrichment pass over one company. Returns human-readable notes."""
    from .founders import extract_founder_signals
    from .funding import extract_funding_signals
    from .market import extract_market_signals
    from .technology import extract_technology_signals
    from .traction import extract_traction_signals

    notes: list[str] = []
    signals = fetch_homepage_signals(startup.website)
    notes.extend(signals.warnings)

    if signals.is_reachable is not None and startup.is_active is None:
        startup.is_active = signals.is_reachable

    if signals.description and not startup.product_summary:
        startup.product_summary = signals.description
        evidence.record(
            startup.id, "product_summary", signals.description,
            source_url=startup.website, source_title="Company homepage",
            source_type=SourceType.COMPANY_WEBSITE,
            verification_status=VerificationStatus.INFERRED,
            note="Homepage meta description — marketing copy, not an independent fact.",
            added_by="enrichment",
        )
        notes.append("Product summary taken from the homepage meta description (INFERRED).")

    corpus = " ".join(
        part for part in [
            startup.product_summary, startup.technology, startup.business_model,
            startup.traction_signals and "; ".join(startup.traction_signals),
            startup.market_size_signal, startup.impact_signal, startup.founder_background,
            signals.body_text,
        ] if part
    )

    for extractor in (
        extract_funding_signals, extract_founder_signals, extract_traction_signals,
        extract_market_signals, extract_technology_signals,
    ):
        notes.extend(extractor(startup, corpus, evidence, source_url=startup.website))

    # Themes may become derivable once we have a product summary.
    if not startup.themes:
        themes = infer_themes(startup.sector, startup.subsector, startup.product_summary,
                              startup.impact_signal)
        if themes:
            startup.themes = themes
            evidence.record(
                startup.id, "themes", themes,
                source_type=SourceType.LLM_INFERENCE,
                verification_status=VerificationStatus.INFERRED,
                note="Themes derived from sector and product text by keyword taxonomy.",
                added_by="enrichment",
            )
            notes.append(f"Themes inferred from text: {', '.join(themes)}.")

    evidence.refresh_startup_confidence(startup)
    return notes


def build_website_evidence(startup: Startup, signals: HomepageSignals) -> list[Evidence]:
    out: list[Evidence] = []
    for field_name, value, note in signals.evidence_tuples():
        out.append(
            Evidence(
                startup_id=startup.id, field_name=field_name, value=value,
                source_url=signals.url, source_title="Company homepage",
                source_type=SourceType.COMPANY_WEBSITE,
                verification_status=VerificationStatus.INFERRED,
                evidence_note=note, added_by="enrichment",
            )
        )
    return out
