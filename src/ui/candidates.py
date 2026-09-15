"""Page 2 — Candidates.

The sortable working table. Everything the investor needs to triage at a glance:
eligibility, score, how much of the score was actually assessable, funding and
whether that funding figure means anything.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models.enums import Dataset, EligibilityStatus
from ..models.startup import Startup
from . import state
from . import theme
from .components import disclaimer, empty_state, provenance_panel


def to_dataframe(startups: list[Startup]) -> pd.DataFrame:
    rows = []
    for s in startups:
        breakdown = s.score_breakdown
        rows.append({
            "Company": s.display_name,
            "Country": s.hq_country or "—",
            "Sector": s.sector or "—",
            "Stage": s.stage.label,
            "Funding (EUR)": s.total_funding_eur,
            "Funding check": s.funding_status.label,
            "Founded": s.founded_year,
            "Eligibility": s.eligibility_status.label,
            "Score": s.score_total,
            "Assessable": f"{breakdown.assessable_weight:.0f}/100" if breakdown else "—",
            "Confidence": round(breakdown.confidence, 2) if breakdown else 0.0,
            "Red flags": s.red_flag_count,
            "Shortlisted": "Yes" if s.shortlisted else "",
            "_id": s.id,
        })
    return pd.DataFrame(rows)


def render() -> None:
    theme.page_header(
        "Stage 02",
        "Candidates",
        "Every company in the workspace, with the two numbers that matter most next to "
        "each score: how much of the framework could actually be assessed, and how well "
        "sourced that assessment is. Sort by any column; select a row to look closer.",
    )
    state.drain_messages()

    if state.dataset() == Dataset.DEMO:
        theme.demo_banner(state.DEMO_BANNER)

    startups = state.startups()
    if not startups:
        empty_state(
            "No companies yet.",
            "Go to Discovery and upload a CSV, add a company by hand, or load the demo set.",
        )
        return

    # ------------------------------------------------------------- filters
    with st.expander("Filter the table", expanded=False):
        cols = st.columns(4)
        status_filter = cols[0].multiselect(
            "Eligibility", options=list(EligibilityStatus),
            format_func=lambda s: s.label,
            default=[EligibilityStatus.ELIGIBLE, EligibilityStatus.NEEDS_REVIEW],
        )
        countries = sorted({s.hq_country for s in startups if s.hq_country})
        country_filter = cols[1].multiselect("Country", options=countries)
        sectors = sorted({s.sector for s in startups if s.sector})
        sector_filter = cols[2].multiselect("Sector", options=sectors)
        min_score = cols[3].slider("Minimum score", 0, 100, 0)
        hide_flagged = st.checkbox("Hide companies with high-severity red flags", value=False)

    filtered = [
        s for s in startups
        if (not status_filter or s.eligibility_status in status_filter)
        and (not country_filter or s.hq_country in country_filter)
        and (not sector_filter or s.sector in sector_filter)
        and ((s.score_total or 0) >= min_score)
    ]
    if hide_flagged:
        filtered = [
            s for s in filtered
            if not any(f.severity.value == "HIGH" and not f.dismissed_by_human
                       for f in s.red_flags)
        ]

    provenance_panel(startups, state.evidence(), key_prefix="cand_")
    st.caption(f"Showing {len(filtered)} of {len(startups)} companies.")
    if not filtered:
        empty_state("No companies match these filters.")
        return

    frame = to_dataframe(filtered)
    display = frame.drop(columns=["_id"])

    event = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Funding (EUR)": st.column_config.NumberColumn(
                "Funding", format="localized", width="small",
                help="Total raised, converted to EUR. Blank means unknown — which is "
                     "never treated as 'below the ceiling'.",
            ),
            "Funding check": st.column_config.TextColumn("Funding check", width="small"),
            "Score": st.column_config.ProgressColumn(
                "Score", min_value=0, max_value=100, format="%.0f", width="medium"
            ),
            "Confidence": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Company": st.column_config.TextColumn("Company", width="medium"),
        },
    )

    selected_rows = event.selection.rows if hasattr(event, "selection") else []
    if selected_rows:
        startup_id = str(frame.iloc[selected_rows[0]]["_id"])
        selected = state.repo().get_startup(startup_id)
        if selected:
            state.select_startup(startup_id)
            st.caption(
                f"{selected.company_name} selected. Open **Company research** for its "
                f"evidence, or **Ranking** to compare it."
            )
            _quick_look(selected)

    theme.rule()
    with st.expander("Export this view"):
        st.download_button(
            "⬇️ Download this view as CSV",
            display.to_csv(index=False),
            f"candidates_{state.dataset().value.lower()}.csv",
            "text/csv",
            width="stretch",
        )


def _quick_look(startup: Startup) -> None:
    cols = st.columns(4)
    cols[0].metric("Score", f"{startup.score_total:.0f}" if startup.score_total is not None else "—")
    cols[1].metric("Eligibility", startup.eligibility_status.value.replace("_", " ").title())
    cols[2].metric("Funding", startup.funding_display())
    cols[3].metric("Red flags", startup.red_flag_count)

    if startup.product_summary:
        st.caption(startup.product_summary[:400])

    with st.expander("Why this eligibility decision?"):
        for reason in startup.eligibility_reasons:
            st.markdown(f"- {reason}")
