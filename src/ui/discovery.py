"""Discovery — define the thesis, then build the pipeline.

Three things had to be true for this page to be useful in a live review:

1. It must never be a dead end. An empty workspace explains what to do next.
2. When the thesis excludes everything, it must say *which filter* did it,
   rather than showing a silent zero.
3. Bringing real data in must not depend on guessing a file's column names.
"""

from __future__ import annotations

from collections import Counter

import streamlit as st

from ..config import DATA_DIR, get_enrichment_settings
from ..ingestion.csv_loader import CSVSourceAdapter, template_csv
from ..ingestion.manual_loader import (
    MANUAL_FORM_FIELDS,
    BulkListAdapter,
    ManualEntryAdapter,
    URLSourceAdapter,
)
from ..ingestion.source_adapter import PLANNED_ADAPTERS
from ..models.enums import CheckOutcome, Dataset, EligibilityStatus, SourceType, Stage
from ..models.thesis import (
    DEFAULT_CHARACTERISTICS,
    DEFAULT_THEMES,
    EUROPE_COUNTRIES,
    InvestmentThesis,
)
from ..pipeline import ingest, reassess_all
from . import import_wizard, sources, state, theme

SAMPLE_CSV = DATA_DIR / "sample_startups.csv"
REAL_CSV = DATA_DIR / "real_startups_2026.csv"

CHECK_LABELS = {
    "geography": "Geography",
    "active": "Company is active",
    "stage": "Stage",
    "funding": "Funding ceiling",
    "theme": "Thesis theme",
    "founded_year": "Founding year",
}


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #

def _filter_diagnostics(startups) -> tuple[Counter, Counter]:
    """Count which eligibility checks are failing and which are unresolved."""
    failed: Counter = Counter()
    unresolved: Counter = Counter()
    for startup in startups:
        if not startup.eligibility_result:
            continue
        for check in startup.eligibility_result.checks:
            if check.outcome == CheckOutcome.FAIL:
                failed[check.check] += 1
            elif check.outcome == CheckOutcome.UNKNOWN:
                unresolved[check.check] += 1
    return failed, unresolved


def _render_diagnostics(startups) -> None:
    """When nothing is eligible, say exactly which filter is responsible."""
    eligible = [s for s in startups if s.eligibility_status == EligibilityStatus.ELIGIBLE]
    if eligible or not startups:
        return

    failed, unresolved = _filter_diagnostics(startups)
    if not failed and not unresolved:
        return

    lines = []
    for check, count in failed.most_common():
        lines.append(
            f"<li><strong>{CHECK_LABELS.get(check, check)}</strong> excludes "
            f"{count} of {len(startups)} companies</li>"
        )
    for check, count in unresolved.most_common():
        lines.append(
            f"<li><strong>{CHECK_LABELS.get(check, check)}</strong> could not be resolved "
            f"for {count} companies — they are held in <em>Needs review</em></li>"
        )

    st.markdown(
        '<div class="vc-callout"><strong>No company currently clears the thesis.</strong> '
        "Here is what is doing the excluding:<ul>" + "".join(lines) + "</ul>"
        "Widen the relevant filter below, or resolve the unknowns on the Company "
        "Research tab.</div>",
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Thesis
# --------------------------------------------------------------------------- #

def _thesis_editor() -> None:
    thesis = state.thesis()

    st.markdown("#### Investment thesis")
    st.markdown(
        f'<div class="vc-lede">Hard filters, applied before any scoring. '
        f'Currently: <strong>{thesis.summary()}</strong></div>',
        unsafe_allow_html=True,
    )

    with st.expander("Edit the thesis", expanded=False):
        with st.form("thesis_form"):
            col1, col2 = st.columns(2)

            with col1:
                geography_mode = st.radio(
                    "Geography",
                    ["Europe (all)", "Specific countries"],
                    index=0 if len(thesis.geographies) == len(EUROPE_COUNTRIES) else 1,
                    horizontal=True,
                )
                countries = st.multiselect(
                    "Countries",
                    options=sorted(EUROPE_COUNTRIES),
                    default=sorted(thesis.geographies)
                    if len(thesis.geographies) < len(EUROPE_COUNTRIES) else [],
                    help="Only applied when 'Specific countries' is selected. "
                         "Narrowing this is the fastest way to end up with zero candidates.",
                )
                stages = st.multiselect(
                    "Stages", options=list(Stage),
                    default=sorted(thesis.stages, key=lambda s: s.value),
                    format_func=lambda s: s.label,
                )
                themes = st.multiselect(
                    "Themes",
                    options=sorted(set(DEFAULT_THEMES) | set(thesis.themes)),
                    default=thesis.themes, accept_new_options=True,
                    help="A company must match at least one to be eligible.",
                )

            with col2:
                max_funding = st.number_input(
                    "Maximum total funding (EUR)", min_value=0, max_value=100_000_000,
                    value=int(thesis.max_total_funding_eur), step=250_000,
                    help="Unknown funding is never assumed to be below this ceiling.",
                )
                use_year_floor = st.checkbox(
                    "Apply a minimum founding year",
                    value=thesis.min_founded_year is not None,
                )
                min_year = st.number_input(
                    "Minimum founding year", min_value=1990, max_value=2030,
                    value=thesis.min_founded_year or 2018, step=1,
                    disabled=not use_year_floor,
                )
                require_active = st.checkbox(
                    "Company must be active", value=thesis.require_active
                )
                characteristics = st.multiselect(
                    "Desired characteristics",
                    options=sorted(set(DEFAULT_CHARACTERISTICS) | set(thesis.characteristics)),
                    default=thesis.characteristics, accept_new_options=True,
                )

            thesis_text = st.text_area(
                "Thesis statement", value=thesis.thesis_text, height=90
            )
            saved = st.form_submit_button(
                "Save thesis and re-evaluate every company", type="primary", width="stretch"
            )

        if saved:
            geographies = (
                set(EUROPE_COUNTRIES) if geography_mode == "Europe (all)" else set(countries)
            )
            if not geographies:
                st.error("Select at least one country, or switch back to 'Europe (all)'.")
                return
            new_thesis = InvestmentThesis(
                name=thesis.name,
                geographies=geographies,
                geography_label="Europe" if geography_mode == "Europe (all)"
                else ", ".join(sorted(geographies)[:4]) + ("…" if len(geographies) > 4 else ""),
                stages=set(stages) or {Stage.PRE_SEED, Stage.SEED},
                themes=themes or list(DEFAULT_THEMES),
                max_total_funding_eur=float(max_funding),
                min_founded_year=int(min_year) if use_year_floor else None,
                require_active=require_active,
                characteristics=characteristics,
                thesis_text=thesis_text,
            )
            state.set_thesis(new_thesis)
            report = reassess_all(
                state.repo(), new_thesis, state.evidence(), state.dataset()
            )
            state.flash(
                f"Thesis saved. Re-evaluated {report.ingested} companies — {report.summary()}",
                "success",
            )
            st.rerun()


# --------------------------------------------------------------------------- #
# Ingestion helpers
# --------------------------------------------------------------------------- #

def _run_ingest(result, enrich: bool = True) -> None:
    for error in result.errors:
        st.error(error)
    if result.errors:
        return

    with st.spinner("Normalising, deduplicating, filtering and scoring…"):
        report = ingest(
            result, state.repo(), state.thesis(), state.evidence(),
            dataset=state.dataset(), enrich=enrich,
        )
    state.reload_evidence()

    st.success(report.summary())
    if report.warnings:
        with st.expander(f"Warnings ({len(report.warnings)})"):
            for warning in report.warnings:
                st.markdown(f"- {warning}")
    if report.notes:
        with st.expander(f"Signals extracted ({len(report.notes)})"):
            for note in report.notes:
                st.markdown(f"- {note}")


def _load_demo() -> None:
    """Load the fictional demo set, switching to the demo dataset first."""
    if state.dataset() != Dataset.DEMO:
        state.set_dataset(Dataset.DEMO)
    result = CSVSourceAdapter().fetch(path=str(SAMPLE_CSV), dataset=Dataset.DEMO)
    _run_ingest(result, enrich=False)


def _load_real() -> None:
    """Load the bundled pipeline of real, source-verified European companies."""
    if state.dataset() != Dataset.REAL:
        state.set_dataset(Dataset.REAL)
    result = CSVSourceAdapter().fetch(
        path=str(REAL_CSV), dataset=Dataset.REAL,
        source_type=SourceType.BUSINESS_MEDIA,
        adapter_label="verified_pipeline_2026",
    )
    _run_ingest(result, enrich=True)


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #

def _manual_tab() -> None:
    st.markdown("#### Add a company by hand")
    st.caption(
        "Everything entered here starts UNVERIFIED. Attach source URLs on the "
        "Company Research tab to raise a field's confidence."
    )
    with st.form("manual_entry", clear_on_submit=True):
        values: dict = {}
        columns = st.columns(2)
        for index, (field_name, label, kind) in enumerate(MANUAL_FORM_FIELDS):
            with columns[index % 2]:
                if kind == "textarea":
                    values[field_name] = st.text_area(label, height=70, key=f"m_{field_name}")
                elif kind == "stage":
                    stage = st.selectbox(label, options=list(Stage),
                                         format_func=lambda s: s.label, key=f"m_{field_name}")
                    values[field_name] = stage.value
                else:
                    values[field_name] = st.text_input(label, key=f"m_{field_name}")
        submitted = st.form_submit_button("Add company", type="primary", width="stretch")

    if submitted:
        _run_ingest(ManualEntryAdapter().fetch(fields=values, dataset=state.dataset()))


def _url_tab() -> None:
    st.markdown("#### Build a research queue from a sourcing list")
    st.caption(
        "Paste the companies you found this morning — one per line, as a URL, a name, "
        "or 'Name, https://url'. Each becomes a skeleton record for you to research. "
        "Nothing beyond what the line literally says is ever inferred."
    )
    bulk = st.text_area(
        "Sourcing list",
        height=150,
        placeholder=(
            "Thermalis GmbH, https://thermalis.example\n"
            "https://ferrivia.example\n"
            "Kassabel Oy"
        ),
        label_visibility="collapsed",
    )
    if bulk.strip():
        count = len([line for line in bulk.splitlines() if line.strip()])
        if st.button(f"Create {count} research record(s)", type="primary", width="stretch"):
            _run_ingest(BulkListAdapter().fetch(text=bulk, dataset=state.dataset()),
                        enrich=False)

    theme.rule()
    st.markdown("#### Add a single company from its website")
    st.caption(
        "Reads the company's own homepage for a title and description. Sector, stage, "
        "funding and founders are left empty on purpose. No third-party database is touched."
    )
    col1, col2 = st.columns([2, 1])
    url = col1.text_input("Company URL", placeholder="https://example.com")
    name = col2.text_input("Company name (optional)")

    if not get_enrichment_settings().fetch_enabled:
        st.caption(
            "Web fetching is off (ENRICHMENT_FETCH_ENABLED=false). A record is still "
            "created, just without the homepage title and description."
        )

    if url and st.button("Add from URL", width="stretch"):
        _run_ingest(
            URLSourceAdapter().fetch(
                url=url, company_name=name or None, dataset=state.dataset()
            )
        )


def _integrations_tab() -> None:
    st.markdown("#### Programmatic integrations")
    st.markdown(
        '<div class="vc-lede">Each of these is a real adapter implementing the same '
        '<code>SourceAdapter</code> interface. None fabricates data: without a configured '
        'key they report themselves unavailable and name the environment variable to set. '
        'That is a deliberate design choice — a scouting tool that invents deal flow is '
        'worse than one that admits it has none.</div>',
        unsafe_allow_html=True,
    )
    for adapter in PLANNED_ADAPTERS:
        available = adapter.is_available()
        status = theme.pill("CONFIGURED" if available else "NOT CONFIGURED",
                            "ELIGIBLE" if available else "NOT_ASSESSED")
        st.markdown(
            f'<div class="vc-source-card"><h5>{adapter.label}</h5>'
            f'<div style="margin:0.35rem 0 0.5rem 0">{status}</div>'
            f'<div class="vc-note"><code>{adapter.env_var}</code> &nbsp;·&nbsp; '
            f'{adapter.docs_url}</div>'
            f'<div class="vc-field-value" style="margin-top:0.5rem">{adapter.notes}</div>'
            "</div>",
            unsafe_allow_html=True,
        )


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

def render() -> None:
    theme.page_header(
        "Stage 01",
        "Discovery",
        "Set the filters that define the fund's mandate, then build a pipeline of real "
        "companies. Everything that arrives is normalised, deduplicated, screened against "
        "the thesis and scored before it appears anywhere else.",
    )
    state.drain_messages()

    if state.dataset() == Dataset.DEMO:
        theme.demo_banner(
            "DEMO DATASET — every company shown is fictional and exists only to exercise "
            "the pipeline. Demo and real companies are stored separately and never mixed."
        )

    startups = state.startups()

    # ------------------------------------------------------------ onboarding
    if not startups:
        st.markdown(
            '<div class="vc-callout"><strong>The workspace is empty.</strong> Three ways to '
            'start.<br><br>'
            '<strong>1. Load the verified pipeline</strong> — 19 real European companies that '
            'raised a pre-seed or seed round under €3M, each one checked against the article '
            'that announced the round. This is the set to present.<br>'
            '<strong>2. Load the demo set</strong> — eight fictional companies that exercise '
            'every path through the pipeline, including the failure cases.<br>'
            '<strong>3. Bring your own</strong> — open <strong>Data sources</strong> below for '
            'the open databases of real European companies, then import a file.</div>',
            unsafe_allow_html=True,
        )
        cols = st.columns([1.3, 1, 1])
        if REAL_CSV.exists():
            if cols[0].button("Load 19 verified real companies", type="primary",
                              width="stretch"):
                _load_real()
                st.rerun()
        if cols[1].button("Load demo set", width="stretch"):
            _load_demo()
            st.rerun()
        cols[2].download_button(
            "Blank CSV template", template_csv(), "startup_template.csv", "text/csv",
            width="stretch",
        )

    theme.rule()
    _thesis_editor()

    # ----------------------------------------------------------------- state
    counts = {"ELIGIBLE": 0, "NEEDS_REVIEW": 0, "INELIGIBLE": 0, "NOT_ASSESSED": 0}
    for startup in startups:
        counts[startup.eligibility_status.value] += 1

    theme.rule()
    st.markdown("#### Pipeline")
    metrics = st.columns(4)
    metrics[0].metric("Candidates", len(startups))
    metrics[1].metric("Eligible", counts["ELIGIBLE"])
    metrics[2].metric("Needs review", counts["NEEDS_REVIEW"])
    metrics[3].metric("Ineligible", counts["INELIGIBLE"])

    _render_diagnostics(startups)

    # ------------------------------------------------------------------ add
    theme.rule()
    st.markdown("#### Add companies")
    tabs = st.tabs([
        "Import a file", "Data sources", "Sourcing list", "Add manually", "Integrations",
    ])
    with tabs[0]:
        import_wizard.render(state.dataset(), _run_ingest)
    with tabs[1]:
        sources.render_catalogue()
    with tabs[2]:
        _url_tab()
    with tabs[3]:
        _manual_tab()
    with tabs[4]:
        _integrations_tab()

    if startups:
        theme.rule()
        with st.expander("Bundled datasets"):
            st.markdown(
                "**Verified pipeline (real).** 19 European companies that announced a "
                "pre-seed or seed round under €3M. Every funding figure is backed by the "
                "URL of the article that published it, so they import VERIFIED. Sourced "
                "from EU-Startups, Tech.eu, ArcticStartup, Femtech Insider and Pulse 2.0 "
                "and checked against each article on 15 September 2026."
            )
            if REAL_CSV.exists() and st.button("Load the verified real pipeline"):
                _load_real()
                st.rerun()
            st.markdown(
                "**Demo set (fictional).** Eight invented companies exercising every "
                "eligibility outcome: clean pass, unknown funding, unsourced funding, over "
                "the ceiling, and a consulting business dressed as SaaS."
            )
            if SAMPLE_CSV.exists() and st.button("Load the fictional demo set"):
                _load_demo()
                st.rerun()
