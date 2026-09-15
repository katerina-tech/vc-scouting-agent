"""Catalogue of real, open data sources for European early-stage companies.

Every entry here is a source an investor can legitimately use today: official,
free, and without violating anyone's terms of service. The application does not
scrape them — it tells you exactly what to download and then imports the file
through the column-mapping wizard.

The ``source_type`` on each entry is what decides the evidence tier, and
therefore the confidence of everything imported from it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import streamlit as st

from ..models.enums import SourceType
from . import theme


@dataclass(frozen=True)
class OpenSource:
    key: str
    name: str
    url: str
    source_type: SourceType
    what: str
    why: str
    how: list[str] = field(default_factory=list)
    caveat: str = ""
    cost: str = "Free"

    @property
    def tier_label(self) -> str:
        return self.source_type.tier.label


CATALOGUE: list[OpenSource] = [
    OpenSource(
        key="epo_deep_tech",
        name="EPO Deep Tech Finder",
        url="https://www.epo.org/en/searching-for-patents/business/deep-tech-finder",
        source_type=SourceType.REGULATORY_RECORD,
        what=(
            "European Patent Office directory of European university spin-outs and "
            "investment-ready startups that hold published patent applications. "
            "Company name, country, technology field, university, patent families."
        ),
        why=(
            "The closest public match to this thesis: European, early-stage, "
            "technology-led. A published patent family is also hard evidence for the "
            "Product / Technical Differentiation criterion — a moat you can verify in a "
            "register rather than a claim on a homepage."
        ),
        how=[
            "Open the Deep Tech Finder dashboard.",
            "Filter by country and technology field to match your thesis.",
            "Export the result table (CSV / Excel).",
            "Import it here and map the columns.",
        ],
        caveat=(
            "Covers only companies with patent applications, so it under-represents "
            "software and marketplace businesses. It carries no funding data — funding "
            "stays UNVERIFIED until you attach a round announcement."
        ),
    ),
    OpenSource(
        key="eic_accelerator",
        name="EIC Accelerator — selected companies",
        url="https://eic.ec.europa.eu/eic-funding-opportunities/eic-accelerator_en",
        source_type=SourceType.REGULATORY_RECORD,
        what=(
            "The European Innovation Council publishes the full list of companies "
            "selected in each cut-off round, with country and the funding awarded."
        ),
        why=(
            "An official European Commission list: Tier 1 provenance, real early-stage "
            "deep-tech companies, and an amount you can cite. A strong starting pool "
            "when the thesis is European and pre-Series A."
        ),
        how=[
            "Open the EIC news page for a recent cut-off round.",
            "Download the linked 'List of selected companies' document.",
            "Copy the table into a spreadsheet and save as CSV.",
            "Import it here; set the source type to 'Regulatory record'.",
        ],
        caveat=(
            "EIC support is grant plus optional equity — it is not a VC round. Record it "
            "as funding only if your thesis ceiling is meant to include non-dilutive money."
        ),
    ),
    OpenSource(
        key="esna",
        name="ESNA Data Platform",
        url="https://data.esnalliance.eu",
        source_type=SourceType.STARTUP_DATABASE,
        what=(
            "European Startup Nations Alliance platform: startup counts, investment "
            "flows and ecosystem indicators across EU member states."
        ),
        why=(
            "Useful for sizing an ecosystem and sanity-checking where the deal flow "
            "actually is before you commit sourcing time to a geography."
        ),
        how=[
            "Browse by country and sector.",
            "Export whatever tables the platform offers.",
        ],
        caveat="Stronger on aggregate statistics than on named individual companies.",
    ),
    OpenSource(
        key="opencorporates",
        name="OpenCorporates",
        url="https://opencorporates.com/",
        source_type=SourceType.REGULATORY_RECORD,
        what=(
            "Legal-entity records drawn from official company registries: incorporation "
            "date, registered address, status, officers."
        ),
        why=(
            "The cleanest way to answer 'is this company actually active, and where is it "
            "really registered?' — which is exactly what the eligibility engine's "
            "geography and active checks need."
        ),
        how=[
            "Search the company name.",
            "Use the registry record to confirm country, incorporation year and status.",
            "Add it as a source on the Company Research tab, field by field.",
        ],
        caveat="No funding, sector or product data. It verifies existence, not promise.",
    ),
    OpenSource(
        key="cordis",
        name="CORDIS / data.europa.eu",
        url="https://cordis.europa.eu/about/services",
        source_type=SourceType.REGULATORY_RECORD,
        what=(
            "Bulk open datasets of every organisation participating in Horizon Europe "
            "and Horizon 2020 projects, in XML, CSV and XLS, with EU contribution amounts."
        ),
        why=(
            "Large, free and official. Good for finding research-heavy SMEs in a specific "
            "technology area, especially in climate and health."
        ),
        how=[
            "Download the organisations dataset for the framework programme.",
            "Filter to SMEs in your target countries.",
            "Import and map the columns.",
        ],
        caveat=(
            "These are research-project participants, not a startup index: universities and "
            "large corporates are mixed in, and an EU contribution is a grant, not a round."
        ),
    ),
    OpenSource(
        key="dealroom",
        name="Dealroom / Crunchbase export",
        url="https://dealroom.co/",
        source_type=SourceType.STARTUP_DATABASE,
        what="Commercial startup databases with funding rounds, investors and stages.",
        why=(
            "If your fund already holds a licence, an export is the fastest route to a "
            "well-populated pipeline: stage and funding arrive already structured."
        ),
        how=[
            "Build the search in Dealroom or Crunchbase using your thesis filters.",
            "Export to CSV.",
            "Import here and map the columns.",
        ],
        caveat=(
            "Requires a paid licence. Do not scrape these sites without one — the adapter "
            "stubs in this application deliberately refuse to fake that access."
        ),
        cost="Licence required",
    ),
]

CATALOGUE_BY_KEY = {s.key: s for s in CATALOGUE}


def render_catalogue() -> None:
    st.markdown("#### Where to get real companies")
    st.markdown(
        '<div class="vc-lede">This application never scrapes third-party databases and '
        'never invents a company. These are the open sources an investor can legitimately '
        'use to build a real pipeline today — download a table, then bring it in through '
        'the import wizard, which maps any column layout.</div>',
        unsafe_allow_html=True,
    )

    for source in CATALOGUE:
        cost_pill = theme.pill(
            source.cost.upper(), "ELIGIBLE" if source.cost == "Free" else "NEEDS_REVIEW"
        )
        tier_pill = theme.pill(source.source_type.tier.value.replace("_", " "), "VERIFIED"
                               if source.source_type.tier.value == "TIER_1" else "MEDIUM")
        st.markdown(
            f'<div class="vc-source-card">'
            f'<h5>{source.name}</h5>'
            f'<div style="margin:0.35rem 0 0.6rem 0">{cost_pill} &nbsp; {tier_pill}</div>'
            f'<div class="vc-field-value">{source.what}</div>'
            f'<div class="vc-note" style="margin-top:0.5rem"><strong>Why it fits:</strong> '
            f'{source.why}</div>'
            + (
                f'<div class="vc-note" style="margin-top:0.4rem"><strong>Caveat:</strong> '
                f'{source.caveat}</div>' if source.caveat else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        with st.expander(f"How to pull data from {source.name}"):
            for index, step in enumerate(source.how, 1):
                st.markdown(f"{index}. {step}")
            st.markdown(f"[Open {source.name}]({source.url})")


def source_type_options() -> list[SourceType]:
    """The source types worth offering in the import wizard, strongest first."""
    return [
        SourceType.REGULATORY_RECORD,
        SourceType.FUNDING_ANNOUNCEMENT,
        SourceType.INVESTOR_ANNOUNCEMENT,
        SourceType.BUSINESS_MEDIA,
        SourceType.STARTUP_DATABASE,
        SourceType.ACCELERATOR_PAGE,
        SourceType.STARTUP_DIRECTORY,
        SourceType.LINKEDIN,
        SourceType.AGGREGATOR,
        SourceType.USER_INPUT,
    ]


def describe_source_type(source_type: SourceType) -> str:
    return f"{source_type.value.replace('_', ' ').title()} — {source_type.tier.label}"
