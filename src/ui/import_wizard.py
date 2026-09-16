"""The import wizard: bring in any table, from any source, with explicit mapping.

The problem this solves: every real data source spells its columns differently.
EPO calls a company "Applicant", the EIC calls it "Beneficiary", Dealroom calls
it "Name". Guessing is fragile and fails silently.

So the wizard does not guess. It reads the file, shows the investor exactly what
columns it found, pre-selects a best guess where the name is recognisable, and
then asks them to confirm the mapping before a single record is created. It also
asks what *kind* of source the file is, because that — not the file format — is
what determines the evidence tier and therefore the confidence of everything
imported from it.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..ingestion.csv_loader import CSVSourceAdapter, apply_mapping, read_table, suggest_mapping
from ..models.enums import Dataset, SourceType
from . import sources, theme

NONE_LABEL = "— not in this file —"

#: ``(model_field, display label, help text, required)``, in mapping-form order.
MAPPABLE_FIELDS: list[tuple[str, str, str, bool]] = [
    ("company_name", "Company name", "The only mandatory column.", True),
    ("website", "Website", "Used to deduplicate companies by domain.", False),
    ("hq_country", "HQ country", "Drives the geography eligibility check.", False),
    ("city", "City", "", False),
    ("founded_year", "Founded year", "Drives the founding-year check.", False),
    ("sector", "Sector", "Mapped onto thesis themes by keyword.", False),
    ("subsector", "Subsector", "", False),
    ("stage", "Stage", "Pre-seed, seed, Series A… Free text is normalised.", False),
    ("total_funding_eur", "Total funding",
     "Any spelling: €1.8M, 1,800,000 EUR, $2m. Unknown stays unknown.", False),
    ("funding_source_url", "Funding source URL",
     "Without this the funding figure can never become VERIFIED.", False),
    ("last_round_eur", "Last round amount", "", False),
    ("last_round_date", "Last round date", "", False),
    ("investors", "Investors", "Semicolon or comma separated.", False),
    ("founders", "Founders", "Semicolon or comma separated.", False),
    ("founder_background", "Founder background", "Drives founder-market fit.", False),
    ("product_summary", "What the company does", "Drives problem magnitude.", False),
    ("business_model", "Business model", "Drives scalability.", False),
    ("customers", "Customers", "Named customers are the strongest traction signal.", False),
    ("traction_signals", "Traction signals", "", False),
    ("technology", "Technology", "", False),
    ("technical_moat", "Technical moat", "Patents, proprietary data, integrations.", False),
    ("competitors", "Competitors", "", False),
    ("market_size_signal", "Market size signal", "Only counts if it contains a figure.", False),
    ("impact_signal", "Impact signal", "", False),
    ("why_now_signal", "Why now", "Regulatory deadlines score highest.", False),
    ("is_active", "Active", "true/false, active/closed.", False),
    ("source_urls", "Source URLs", "Applied to the whole row as provenance.", False),
    ("notes", "Notes", "", False),
]

CORE_FIELDS = {
    "company_name", "website", "hq_country", "founded_year", "sector", "stage",
    "total_funding_eur", "funding_source_url", "product_summary",
}


def _state_key(suffix: str) -> str:
    return f"import_wizard_{suffix}"


def reset_wizard() -> None:
    for suffix in ("frame", "filename", "mapping", "source_type"):
        st.session_state.pop(_state_key(suffix), None)


def render(dataset: Dataset, on_import) -> None:
    """Render the wizard. ``on_import(result)`` receives the IngestionResult."""
    st.markdown("#### Step 1 — choose a file")
    st.caption(
        "CSV, TSV or Excel, from any source. Separator and encoding are detected "
        "automatically, so a semicolon-separated European export works as-is."
    )

    uploaded = st.file_uploader(
        "Data file", type=["csv", "tsv", "txt", "xlsx", "xlsm", "xls"],
        label_visibility="collapsed", key="import_file",
    )

    if uploaded is None:
        st.markdown(
            '<div class="vc-callout">No file yet. If you do not have one, open the '
            '<strong>Data sources</strong> tab — it lists the open, free databases of real '
            'European companies and exactly what to download from each.</div>',
            unsafe_allow_html=True,
        )
        return

    frame, error = read_table(content=uploaded.getvalue(), filename=uploaded.name)
    if frame is None:
        st.error(error)
        return
    if frame.empty:
        st.warning("That file has no rows in it.")
        return

    st.success(
        f"Read **{len(frame):,} rows** and **{len(frame.columns)} columns** "
        f"from `{uploaded.name}`."
    )

    with st.expander("Preview the raw file", expanded=False):
        st.dataframe(frame.head(8), width="stretch", hide_index=True)

    theme.rule()

    # ---------------------------------------------------------------- step 2
    st.markdown("#### Step 2 — what kind of source is this?")
    st.caption(
        "This sets the evidence tier for every field imported from the file, and "
        "therefore how confident the application is allowed to be about it. An "
        "official register is Tier 1; a directory export is Tier 3."
    )
    options = sources.source_type_options()
    source_type = st.selectbox(
        "Source type", options=options,
        format_func=sources.describe_source_type,
        index=options.index(SourceType.STARTUP_DATABASE),
        label_visibility="collapsed",
    )

    theme.rule()

    # ---------------------------------------------------------------- step 3
    st.markdown("#### Step 3 — map the columns")
    st.caption(
        "Recognisable column names are pre-selected. Everything else is left blank "
        "on purpose: an unmapped column is ignored, never guessed at."
    )

    columns = [str(c) for c in frame.columns]
    choices = [NONE_LABEL] + columns
    guessed = suggest_mapping(columns)

    show_all = st.toggle(
        "Show every mappable field",
        value=False,
        help="Off shows the fields that drive eligibility and scoring; on shows all 28.",
    )
    fields = [
        f for f in MAPPABLE_FIELDS
        if show_all or f[0] in CORE_FIELDS or guessed.get(f[0])
    ]

    mapping: dict[str, str] = {}
    left, right = st.columns(2)
    for index, (field_name, label, help_text, required) in enumerate(fields):
        container = left if index % 2 == 0 else right
        with container:
            default = guessed.get(field_name)
            selected = st.selectbox(
                label + (" *" if required else ""),
                options=choices,
                index=choices.index(default) if default in choices else 0,
                help=help_text or None,
                key=f"map_{field_name}",
            )
            if selected != NONE_LABEL:
                mapping[field_name] = selected

    matched = len(mapping)
    if not mapping.get("company_name"):
        st.error("Map a column to **Company name** — nothing can be imported without it.")
        return

    if not mapping.get("funding_source_url"):
        st.markdown(
            '<div class="vc-callout">No <strong>Funding source URL</strong> column is '
            'mapped. Any funding figure in this file will be imported as UNVERIFIED, and '
            'the companies will land in <em>Needs review</em> rather than <em>Eligible</em>. '
            'That is deliberate: a number without a source cannot clear a funding ceiling.'
            '</div>',
            unsafe_allow_html=True,
        )

    theme.rule()

    # ---------------------------------------------------------------- step 4
    st.markdown("#### Step 4 — check and import")
    st.caption(f"{matched} column(s) mapped. Preview of the first rows as they will be read:")

    try:
        preview = apply_mapping(frame, mapping).head(5)
        st.dataframe(preview, width="stretch", hide_index=True)
    except Exception as exc:  # noqa: BLE001
        st.error(
            "Could not apply that mapping — one of the selected columns doesn't match "
            "the data. Try a different column, or check the file for stray rows."
        )
        with st.expander("Technical details"):
            st.code(str(exc))
        return

    cols = st.columns([1, 1, 2])
    enrich = cols[1].toggle(
        "Extract signals after import", value=True,
        help="Reads the text you imported for traction, moat and timing signals. "
             "Only fetches company websites if enrichment is enabled in .env.",
    )

    if cols[0].button("Import companies", type="primary", width="stretch"):
        result = CSVSourceAdapter().fetch(
            content=uploaded.getvalue(),
            filename=uploaded.name,
            dataset=dataset,
            mapping=mapping,
            source_type=source_type,
            adapter_label=f"import:{source_type.value.lower()}",
        )
        on_import(result, enrich)


def mapping_summary(mapping: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Field": field, "Column in file": column} for field, column in mapping.items()]
    )
