"""Page 3 — Company Research.

Every section shows value · verification status · confidence · clickable source.
This is also where the human-in-the-loop lives: edit a field, attach a source,
mark evidence verified, approve a Needs-review company, add a note.
"""

from __future__ import annotations

import streamlit as st

from ..enrichment.company_enrichment import enrich_company
from ..filters.eligibility import apply_eligibility
from ..models.enums import EligibilityStatus, Stage
from ..models.startup import Startup
from ..normalization.company_normalizer import normalize_funding, normalize_stage
from ..research.red_flags import apply_red_flags
from ..scoring.score_engine import apply_score
from . import state, theme
from .components import (
    add_source_form,
    confidence_legend,
    disclaimer,
    empty_state,
    field_block,
    render_red_flags,
)

SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Company overview", [
        ("company_name", "Company name"), ("website", "Website"),
        ("hq_country", "HQ country"), ("city", "City"),
        ("founded_year", "Founded"), ("sector", "Sector"),
        ("subsector", "Subsector"), ("themes", "Thesis themes"),
        ("is_active", "Active"),
    ]),
    ("Founders", [("founders", "Founders"), ("founder_background", "Background")]),
    ("Product", [
        ("product_summary", "What they do"), ("business_model", "Business model"),
    ]),
    ("Funding", [
        ("stage", "Stage"), ("total_funding_eur", "Total funding (EUR)"),
        ("last_round_eur", "Last round (EUR)"), ("last_round_date", "Last round date"),
    ]),
    ("Investors", [("investors", "Investors")]),
    ("Traction", [("traction_signals", "Traction signals"), ("customers", "Customers")]),
    ("Technology", [("technology", "Technology"), ("technical_moat", "Technical moat")]),
    ("Market", [("market_size_signal", "Market size signal"), ("why_now_signal", "Why now")]),
    ("Competition", [("competitors", "Competitors")]),
    ("Impact", [("impact_signal", "Impact signal")]),
]

EDITABLE_FIELDS = [
    "company_name", "website", "hq_country", "city", "founded_year", "sector",
    "subsector", "stage", "total_funding_eur", "product_summary", "business_model",
    "founder_background", "technology", "technical_moat", "market_size_signal",
    "impact_signal", "why_now_signal",
]

SOURCEABLE_FIELDS = [
    "total_funding_eur", "last_round_eur", "stage", "hq_country", "founded_year",
    "founders", "founder_background", "customers", "traction_signals", "investors",
    "product_summary", "technology", "technical_moat", "market_size_signal",
    "impact_signal", "why_now_signal", "is_active",
]


def _reassess(startup: Startup) -> None:
    apply_eligibility(startup, state.thesis(), state.evidence())
    apply_score(startup, state.thesis(), state.evidence())
    apply_red_flags(startup, state.thesis(), state.evidence())
    state.repo().save_startup(startup)


def _header(startup: Startup) -> None:
    if startup.is_demo:
        theme.demo_banner("DEMO DATA — this is a fictional company.")

    st.markdown(f"# {startup.company_name}")
    if startup.website:
        st.markdown(f"[{startup.website}]({startup.website})")

    cols = st.columns(5)
    cols[0].metric("Score", f"{startup.score_total:.0f}" if startup.score_total is not None else "—")
    cols[1].metric("Eligibility", startup.eligibility_status.value.replace("_", " ").title())
    cols[2].metric("Funding", startup.funding_display(), help=startup.funding_status.label)
    cols[3].metric("Data confidence", startup.data_confidence.value.title())
    cols[4].metric("Red flags", startup.red_flag_count)

    with st.expander("Eligibility decision", expanded=startup.eligibility_status != EligibilityStatus.ELIGIBLE):
        if startup.eligibility_result:
            for check in startup.eligibility_result.checks:
                st.markdown(f"- {check.display}")
        else:
            st.caption("Not assessed yet.")

        if startup.eligibility_status == EligibilityStatus.NEEDS_REVIEW:
            st.divider()
            approved = st.checkbox(
                "I have reviewed this company and approve it for ranking",
                value=startup.manual_eligibility_approved,
                help="Needs-review companies are excluded from ranking until a human approves them.",
            )
            if approved != startup.manual_eligibility_approved:
                startup.record_override(
                    "manual_eligibility_approved", approved,
                    reason="Investor reviewed the unresolved eligibility checks.",
                )
                state.repo().save_startup(startup)
                state.repo().save_override(startup.id, startup.human_overrides[-1])
                st.rerun()

        if startup.eligibility_status == EligibilityStatus.INELIGIBLE:
            theme.callout(
                "<strong>Ineligible.</strong> This company cannot be ranked or shortlisted. "
                "Correct the underlying data below if you believe a check is wrong."
            )


def _evidence_sections(startup: Startup) -> None:
    evidence = state.evidence()
    confidence_legend()

    for section_name, fields in SECTIONS:
        with st.expander(section_name, expanded=section_name in {"Company overview", "Funding"}):
            for field_name, label in fields:
                value = getattr(startup, field_name, None)
                if field_name == "stage":
                    value = startup.stage.label
                assessment = evidence.assess(startup, field_name, value)
                field_block(label, assessment, startup=startup, evidence=evidence)


def _edit_form(startup: Startup) -> None:
    st.markdown("#### Correct the record")
    st.caption("Every edit is stored as an override with a reason, and can be audited later.")

    with st.form(f"edit_{startup.id}"):
        field_name = st.selectbox("Field", options=EDITABLE_FIELDS)
        current = getattr(startup, field_name, None)
        if field_name == "stage":
            current = startup.stage.label
        st.caption(f"Current value: `{current}`")
        new_value = st.text_input("New value")
        reason = st.text_input("Reason for the change")
        submitted = st.form_submit_button("Apply override", width="stretch")

    if not submitted:
        return
    if not new_value.strip():
        st.error("Enter a new value.")
        return

    parsed: object = new_value.strip()
    try:
        if field_name in {"total_funding_eur", "last_round_eur"}:
            parsed = normalize_funding(new_value)["amount_eur"]
            if parsed is None:
                st.error(f"Could not parse {new_value!r} as an amount.")
                return
        elif field_name == "founded_year":
            parsed = int(new_value.strip())
        elif field_name == "stage":
            parsed = normalize_stage(new_value)
            if parsed == Stage.UNKNOWN:
                st.error(f"Could not map {new_value!r} to a known stage.")
                return
    except ValueError:
        st.error(f"Could not parse {new_value!r} for {field_name}.")
        return

    startup.record_override(field_name, parsed, reason=reason or "No reason given.")
    state.repo().save_override(startup.id, startup.human_overrides[-1])
    _reassess(startup)
    st.success(f"{field_name} updated and the company re-evaluated.")
    st.rerun()


def _notes(startup: Startup) -> None:
    st.markdown("#### Notes")
    with st.form(f"note_{startup.id}", clear_on_submit=True):
        body = st.text_area("Add a note", height=90, label_visibility="collapsed",
                            placeholder="What did you find? What still bothers you?")
        if st.form_submit_button("Save note", width="stretch") and body.strip():
            state.repo().add_note(startup.id, body.strip())
            startup.investor_notes.append(body.strip())
            state.repo().save_startup(startup)
            st.rerun()

    for note in state.repo().list_notes(startup.id):
        st.markdown(f"> {note['body']}")
        st.caption(f"{note['author']} · {note['created_at'][:16].replace('T', ' ')}")


def render() -> None:
    theme.page_header(
        "Stage 03",
        "Company research",
        "Every field shown with its verification status, its confidence and the source "
        "behind it. This is also where an investor corrects the record, attaches a source, "
        "or approves a company the filters could not resolve.",
    )
    state.drain_messages()

    startups = state.startups()
    if not startups:
        empty_state("No companies yet.", "Add some on the Discovery tab first.")
        return

    ids = [s.id for s in startups]
    labels = {s.id: f"{s.display_name} — {s.eligibility_status.label}" for s in startups}
    current = state.selected_startup()
    index = ids.index(current.id) if current and current.id in ids else 0

    chosen_id = st.selectbox(
        "Company", options=ids, index=index, format_func=lambda i: labels[i],
        label_visibility="collapsed",
    )
    if chosen_id != (current.id if current else None):
        state.select_startup(chosen_id)
    startup = state.repo().get_startup(chosen_id)
    if startup is None:
        empty_state("That company no longer exists.")
        return

    theme.rule()
    _header(startup)

    action_cols = st.columns(3)
    if action_cols[0].button("Re-run scoring", width="stretch"):
        _reassess(startup)
        st.success("Re-evaluated against the current thesis.")
        st.rerun()
    if action_cols[1].button("Re-extract signals", width="stretch"):
        notes = enrich_company(startup, state.evidence())
        _reassess(startup)
        state.repo().save_evidence_many(state.evidence().for_startup(startup.id))
        for note in notes:
            st.caption(f"• {note}")
        st.success("Signal extraction complete.")
    if startup.is_rankable:
        if action_cols[2].button(
            "Remove from shortlist" if startup.shortlisted else "Add to final shortlist",
            width="stretch", type="primary" if not startup.shortlisted else "secondary",
        ):
            if startup.shortlisted:
                state.repo().remove_from_shortlist(startup.id)
            else:
                state.repo().add_to_shortlist(startup.id)
            st.rerun()

    theme.rule()
    tabs = st.tabs(["Evidence", "Red flags", "Edit and sources", "Notes", "Audit trail"])

    with tabs[0]:
        _evidence_sections(startup)

    with tabs[1]:
        st.caption(
            "Red flags are shown beside the score, never subtracted from it. Dismissing one "
            "records your judgement; it does not delete the finding."
        )
        dismissed = render_red_flags(startup.red_flags, key_prefix="research_")
        if dismissed:
            for flag in startup.red_flags:
                if flag.code in dismissed:
                    flag.dismissed_by_human = True
            state.repo().save_startup(startup)
            st.rerun()

        if startup.open_questions:
            st.markdown("#### Open questions this raises")
            for question in startup.open_questions:
                st.markdown(f"- {question}")

    with tabs[2]:
        left, right = st.columns(2)
        with left:
            _edit_form(startup)
        with right:
            if add_source_form(startup, state.evidence(), SOURCEABLE_FIELDS):
                state.repo().save_evidence_many(state.evidence().for_startup(startup.id))
                state.evidence().refresh_startup_confidence(startup)
                _reassess(startup)
                st.success("Source added. Confidence and eligibility recalculated.")
                st.rerun()

    with tabs[3]:
        _notes(startup)

    with tabs[4]:
        overrides = state.repo().list_overrides(startup.id)
        if not overrides:
            st.caption("No overrides recorded for this company.")
        for row in overrides:
            st.markdown(
                f"**{row['field_name']}** — `{row['old_value']}` → `{row['new_value']}`"
            )
            st.caption(f"{row['author']} · {row['created_at'][:16].replace('T', ' ')} · {row['reason']}")
