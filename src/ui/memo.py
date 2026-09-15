"""Page 5 — Investment Memo.

Structure and recommendation are computed deterministically; the prose is
LLM-written when a model is configured. The recommendation tops out at
INVESTIGATE by design.
"""

from __future__ import annotations

import streamlit as st

from ..models.enums import Recommendation
from ..models.startup import Startup
from ..reports.investment_memo import SECTION_ORDER, generate_memo
from ..reports.loom_script import generate_loom_script, structure_checklist
from . import state, theme
from .components import disclaimer, empty_state

RECOMMENDATION_STATUS = {
    Recommendation.INVESTIGATE: "INVESTIGATE",
    Recommendation.WATCH: "WATCH",
    Recommendation.PASS_: "PASS",
}


def _render_memo(startup: Startup) -> None:
    cache = st.session_state.memo_cache
    memo = cache.get(startup.id)

    cols = st.columns([1, 1, 2])
    if cols[0].button("Generate memo", type="primary", width="stretch"):
        with st.spinner("Assembling the memo from the evidence…"):
            memo = generate_memo(startup, state.thesis(), state.evidence(), state.analyst())
        cache[startup.id] = memo
        state.repo().save_startup(startup)
    if memo and cols[1].button("Regenerate", width="stretch"):
        with st.spinner("Regenerating…"):
            memo = generate_memo(startup, state.thesis(), state.evidence(), state.analyst())
        cache[startup.id] = memo

    if memo is None:
        st.caption("Generate a memo to see it here.")
        return

    badge = theme.pill(
        memo.recommendation.value, RECOMMENDATION_STATUS[memo.recommendation]
    )
    st.markdown(
        f'<div class="vc-callout">{badge} &nbsp; <strong>'
        f'{memo.recommendation.label}</strong>'
        f'<div class="vc-note" style="margin-top:0.4rem">{memo.recommendation_reason}</div>'
        f'<div class="vc-note">There is deliberately no automatic INVEST verdict. The '
        f'strongest recommendation this tool produces is INVESTIGATE.</div></div>',
        unsafe_allow_html=True,
    )

    metrics = st.columns(4)
    metrics[0].metric("Score", f"{memo.score_total:.0f}/100" if memo.score_total is not None else "—")
    metrics[1].metric("Assessable", f"{memo.evidence_coverage:.0%}")
    metrics[2].metric("Confidence", f"{memo.confidence:.2f}")
    metrics[3].metric("Red flags", len(memo.red_flags))

    st.caption(memo.generator_note)
    theme.rule()

    for key, heading in SECTION_ORDER:
        st.markdown(f"### {heading}")
        st.markdown(memo.sections.get(key) or "_Insufficient public evidence._")

    if memo.red_flags:
        st.markdown("### Red flags")
        for flag in memo.red_flags:
            st.markdown(f"- {flag}")

    if memo.questions_for_founders:
        st.markdown("### Questions for founders")
        for i, question in enumerate(memo.questions_for_founders, 1):
            st.markdown(f"{i}. {question}")

    if memo.sources:
        st.markdown("### Sources")
        for url in memo.sources:
            st.markdown(f"- [{url}]({url})")

    theme.rule()
    st.download_button(
        "Download memo (Markdown)",
        memo.to_markdown(),
        f"memo_{startup.normalized_name or startup.id}.md",
        "text/markdown",
        width="stretch",
    )


def _render_loom(startup: Startup) -> None:
    st.markdown("### Loom application script")
    st.caption(
        "A 45-60 second spoken pitch: why you would investigate this company. "
        "Target length is 110-150 words at ~150 words per minute."
    )
    with st.expander("The seven beats"):
        for i, beat in enumerate(structure_checklist(), 1):
            st.markdown(f"{i}. {beat}")

    cache = st.session_state.loom_cache
    pitch = cache.get(startup.id)

    if st.button("Generate Loom script", width="stretch", type="primary"):
        memo = st.session_state.memo_cache.get(startup.id)
        with st.spinner("Writing the script…"):
            pitch = generate_loom_script(
                startup, state.thesis(), state.evidence(), state.analyst(),
                memo.to_markdown() if memo else "",
            )
        cache[startup.id] = pitch

    if pitch is None:
        return

    cols = st.columns(3)
    cols[0].metric("Words", pitch.word_count)
    cols[1].metric("Spoken", f"~{pitch.estimated_seconds}s")
    cols[2].metric("In window", "Yes" if pitch.within_target else "No")

    for warning in pitch.warnings:
        st.caption(warning)

    st.text_area("Script", pitch.script, height=260, label_visibility="collapsed")
    st.download_button(
        "Download script",
        pitch.to_markdown(),
        f"loom_{startup.normalized_name or startup.id}.md",
        "text/markdown",
        width="stretch",
    )


def render() -> None:
    theme.page_header(
        "Stage 05",
        "Investment memo",
        "Structure and recommendation are computed from the evidence; the prose is written "
        "by the analyst model when one is configured, and deterministically when not.",
    )
    state.drain_messages()

    startups = state.startups()
    if not startups:
        empty_state("No companies yet.", "Add some on the Discovery tab first.")
        return

    shortlisted = [s for s in startups if s.shortlisted]
    options = shortlisted + [s for s in startups if not s.shortlisted]
    ids = [s.id for s in options]
    def _label(s) -> str:
        star = "[shortlisted] " if s.shortlisted else ""
        score = f"{s.score_total:.0f}/100" if s.score_total is not None else "unscored"
        return f"{star}{s.display_name} — {score}"

    labels = {s.id: _label(s) for s in options}

    current = state.selected_startup()
    index = ids.index(current.id) if current and current.id in ids else 0
    chosen = st.selectbox("Company", options=ids, index=index,
                          format_func=lambda i: labels[i], label_visibility="collapsed")
    state.select_startup(chosen)
    startup = state.repo().get_startup(chosen)
    if startup is None:
        return

    if startup.is_demo:
        theme.demo_banner("DEMO DATA — this memo describes a fictional company.")

    if not state.analyst().available:
        st.caption(
            f"{state.analyst().describe()} The memo below is written deterministically "
            "from the evidence record: complete, just less fluent."
        )

    tabs = st.tabs(["Memo", "Loom script"])
    with tabs[0]:
        _render_memo(startup)
    with tabs[1]:
        _render_loom(startup)
