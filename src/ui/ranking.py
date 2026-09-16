"""Page 4 — Ranking.

Only eligible companies, or Needs-review companies a human has explicitly
approved, are ranked. The breakdown is always visible, and any criterion can be
overridden by the investor with a reason.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models.enums import EligibilityStatus
from ..models.startup import Startup
from ..scoring.score_config import CRITERIA, weights_table
from ..scoring.score_engine import override_criterion, rank
from . import state
from . import theme
from .components import (
    disclaimer, empty_state, funnel_chart, render_criterion, score_chart, score_table,
)

COLUMN_CRITERIA = [
    ("thesis_fit", "Thesis"),
    ("problem_magnitude", "Market"),
    ("founder_market_fit", "Team"),
    ("product_differentiation", "Tech"),
    ("traction", "Traction"),
    ("why_now", "Why now"),
]


def ranking_frame(ranked: list[Startup]) -> pd.DataFrame:
    rows = []
    for position, s in enumerate(ranked, 1):
        breakdown = s.score_breakdown
        row = {
            "Rank": position,
            "Company": s.display_name,
            "Total": s.score_total,
        }
        for key, label in COLUMN_CRITERIA:
            row[label] = breakdown.score_for(key) if breakdown else 0.0
        row["Confidence"] = round(breakdown.confidence, 2) if breakdown else 0.0
        row["Assessable"] = f"{breakdown.assessable_weight:.0f}/100" if breakdown else "—"
        row["Red flags"] = s.red_flag_count
        row["Shortlisted"] = "Yes" if s.shortlisted else ""
        row["_id"] = s.id
        rows.append(row)
    return pd.DataFrame(rows)


def _override_panel(startup: Startup) -> None:
    st.markdown("#### Override a criterion")
    st.caption(
        "Use this when you know something the evidence does not show. The override is "
        "recorded with your reason and marked as an investor override in the breakdown."
    )
    with st.form(f"override_{startup.id}"):
        cols = st.columns([2, 1])
        criterion = cols[0].selectbox(
            "Criterion", options=[c.key for c in CRITERIA],
            format_func=lambda k: next(c.label for c in CRITERIA if c.key == k),
        )
        rating = cols[1].slider("Rating (0-5)", 0, 5, 3)
        reason = st.text_input("Why? (required)")
        submitted = st.form_submit_button("Apply override", width="stretch")

    if submitted:
        if not reason.strip():
            st.error("An override needs a reason — that is the point of recording it.")
            return
        override_criterion(startup, criterion, rating, reason.strip())
        state.repo().save_startup(startup)
        state.repo().save_override(startup.id, startup.human_overrides[-1])
        st.success("Override applied and recorded.")
        st.rerun()


def render() -> None:
    theme.page_header(
        "Stage 04",
        "Ranking",
        "Only eligible companies are ranked, plus any needs-review company an investor has "
        "personally approved. A well-evidenced score outranks a speculative one of the "
        "same value.",
    )
    state.drain_messages()

    startups = state.startups()
    if not startups:
        empty_state("No companies yet.", "Add some on the Discovery tab first.")
        return

    shortlisted = len([s for s in startups if s.shortlisted])
    st.markdown("#### From the sourced pipeline to a shortlist")
    funnel_chart(startups, shortlisted, key="funnel_ranking")
    theme.rule()

    ranked = rank(startups)
    blocked = [
        s for s in startups
        if s.eligibility_status == EligibilityStatus.NEEDS_REVIEW
        and not s.manual_eligibility_approved
    ]

    if blocked:
        st.info(
            f"{len(blocked)} company/companies are held back pending your review: "
            + ", ".join(s.company_name for s in blocked[:6])
            + ("…" if len(blocked) > 6 else "")
            + ". Approve them on the Company Research tab to include them here.",
        )

    if not ranked:
        empty_state(
            "Nothing is rankable yet.",
            "A company must be ELIGIBLE, or a NEEDS_REVIEW company you have approved.",
        )
        with st.expander("The scoring framework"):
            st.dataframe(pd.DataFrame(weights_table()), hide_index=True, width="stretch")
        return

    frame = ranking_frame(ranked)
    display = frame.drop(columns=["_id"])

    event = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Company": st.column_config.TextColumn("Company", width="medium"),
            "Total": st.column_config.ProgressColumn(
                "Total", min_value=0, max_value=100, format="%.0f", width="medium"
            ),
            "Confidence": st.column_config.NumberColumn(format="%.2f", width="small"),
            "Rank": st.column_config.NumberColumn("Rank", width="small"),
        },
    )

    with st.expander("How the 100 points are allocated"):
        st.dataframe(pd.DataFrame(weights_table()), hide_index=True, width="stretch")
        st.caption(
            "Each criterion's points = its 0-5 rating ÷ 5, times its weight. A criterion "
            "with no evidence is left unrated and contributes nothing — it is not quietly "
            "scored 0 or 3."
        )

    rows = event.selection.rows if hasattr(event, "selection") else []
    if not rows:
        st.caption("Select a row to see its full breakdown and add it to the shortlist.")
        return

    startup = state.repo().get_startup(str(frame.iloc[rows[0]]["_id"]))
    if startup is None or startup.score_breakdown is None:
        return

    state.select_startup(startup.id)
    theme.rule()
    st.markdown(f"## {startup.display_name}")

    cols = st.columns(4)
    cols[0].metric("Total score", f"{startup.score_total:.0f}/100")
    cols[1].metric("Assessable", f"{startup.score_breakdown.assessable_weight:.0f}/100")
    cols[2].metric("Evidence coverage", f"{startup.score_breakdown.evidence_coverage:.0%}")
    cols[3].metric("Confidence", f"{startup.score_breakdown.confidence:.2f}")

    if startup.score_breakdown.notes:
        for note in startup.score_breakdown.notes:
            theme.callout(note)

    score_chart(startup.score_breakdown, key=f"chart_{startup.id}")

    st.markdown("### Breakdown")
    for criterion in startup.score_breakdown.criteria:
        render_criterion(criterion, state.evidence())
        st.divider()

    with st.expander("Breakdown as a table"):
        st.dataframe(score_table(startup.score_breakdown), hide_index=True,
                     width="stretch")

    left, right = st.columns(2)
    with left:
        _override_panel(startup)
    with right:
        st.markdown("#### Final shortlist")
        st.caption("The shortlist is where 2-5 companies get compared side by side.")
        if startup.shortlisted:
            st.caption("Already on the shortlist.")
            if st.button("Remove from shortlist", width="stretch"):
                state.repo().remove_from_shortlist(startup.id)
                st.rerun()
        else:
            note = st.text_input("Why this one? (optional)", key=f"sl_note_{startup.id}")
            if st.button("Add to final shortlist", type="primary", width="stretch"):
                state.repo().add_to_shortlist(startup.id, note)
                st.success(f"{startup.company_name} added to the shortlist.")
                st.rerun()
