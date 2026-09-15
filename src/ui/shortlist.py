"""Page 6 — Final Shortlist.

The output of the whole exercise: 2-5 companies compared side by side, with an
explanation of why each one is worth an investigation, and a CSV export.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models.startup import Startup
from ..reports.investment_memo import decide_recommendation, generate_memo
from ..reports.loom_script import generate_loom_script
from . import state, theme
from .components import disclaimer, empty_state, funnel_chart, provenance_panel

COMPARISON_ROWS: list[tuple[str, str]] = [
    ("problem", "Problem"),
    ("market", "Market"),
    ("funding", "Funding"),
    ("founder_market_fit", "Founder-Market Fit"),
    ("traction", "Traction"),
    ("technical_moat", "Technical Moat"),
    ("thesis_fit", "Thesis Fit"),
    ("why_now", "Why Now"),
    ("total_score", "Total Score"),
    ("confidence", "Confidence"),
    ("main_risk", "Main Risk"),
]


def _truncate(text: str | None, limit: int = 160) -> str:
    if not text:
        return "—"
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _cell(startup: Startup, key: str) -> str:
    breakdown = startup.score_breakdown

    if key == "problem":
        return _truncate(startup.product_summary)
    if key == "market":
        return _truncate(startup.market_size_signal)
    if key == "funding":
        return f"{startup.funding_display()} ({startup.funding_status.value})"
    if key == "founder_market_fit":
        score = f"{breakdown.score_for('founder_market_fit'):.0f}/15" if breakdown else "—"
        return f"{score} · {_truncate(startup.founder_background, 110)}"
    if key == "traction":
        if startup.customers:
            return f"{len(startup.customers)} named customer(s): {_truncate(', '.join(startup.customers), 100)}"
        return _truncate("; ".join(startup.traction_signals) or None, 130)
    if key == "technical_moat":
        score = f"{breakdown.score_for('product_differentiation'):.0f}/15" if breakdown else "—"
        return f"{score} · {_truncate(startup.technical_moat, 110)}"
    if key == "thesis_fit":
        score = f"{breakdown.score_for('thesis_fit'):.0f}/20" if breakdown else "—"
        return f"{score} · {', '.join(startup.themes) or 'no theme mapped'}"
    if key == "why_now":
        return _truncate(startup.why_now_signal, 130)
    if key == "total_score":
        if startup.score_total is None:
            return "—"
        assessable = f" (of {breakdown.assessable_weight:.0f} assessable)" if breakdown else ""
        return f"{startup.score_total:.0f}/100{assessable}"
    if key == "confidence":
        return f"{breakdown.confidence:.2f} ({startup.data_confidence.value})" if breakdown else "—"
    if key == "main_risk":
        active = [f for f in startup.red_flags if not f.dismissed_by_human]
        if not active:
            return "No red flags recorded"
        worst = sorted(active, key=lambda f: {"HIGH": 0, "MEDIUM": 1, "INFO": 2}[f.severity.value])[0]
        return f"{worst.severity.label} {worst.title}"
    return "—"


def comparison_frame(shortlist: list[Startup]) -> pd.DataFrame:
    data = {"": [label for _, label in COMPARISON_ROWS]}
    for startup in shortlist:
        data[startup.display_name] = [_cell(startup, key) for key, _ in COMPARISON_ROWS]
    return pd.DataFrame(data)


def export_frame(shortlist: list[Startup]) -> pd.DataFrame:
    rows = []
    for startup in shortlist:
        breakdown = startup.score_breakdown
        recommendation, reason = decide_recommendation(startup)
        rows.append({
            "Company": startup.company_name,
            "Dataset": startup.dataset.value,
            "Website": startup.website or "",
            "Country": startup.hq_country or "",
            "Stage": startup.stage.label,
            "Total funding (EUR)": startup.total_funding_eur,
            "Funding verification": startup.funding_status.value,
            "Problem": startup.product_summary or "",
            "Market": startup.market_size_signal or "",
            "Founder-Market Fit": startup.founder_background or "",
            "Traction": "; ".join(startup.traction_signals),
            "Technical moat": startup.technical_moat or "",
            "Thesis themes": ", ".join(startup.themes),
            "Why now": startup.why_now_signal or "",
            "Total score": startup.score_total,
            "Assessable points": breakdown.assessable_weight if breakdown else None,
            "Evidence coverage": breakdown.evidence_coverage if breakdown else None,
            "Confidence": breakdown.confidence if breakdown else None,
            "Red flags": "; ".join(f.title for f in startup.red_flags if not f.dismissed_by_human),
            "Recommendation": recommendation.value,
            "Recommendation reason": reason,
            "Sources": "; ".join(startup.source_urls),
        })
    return pd.DataFrame(rows)


def render() -> None:
    theme.page_header(
        "Stage 06",
        "Final shortlist",
        "The deliverable: two to five companies worth an investigation, with the evidence "
        "behind every claim and the questions still open.",
    )
    state.drain_messages()

    shortlist = [s for s in state.repo().list_shortlist() if s.dataset == state.dataset()]

    if not shortlist:
        empty_state(
            "Nothing shortlisted yet.",
            "Rank the candidates, open one, and use 'Add to final shortlist'.",
        )
        return

    if len(shortlist) > 5:
        st.warning(
            f"{len(shortlist)} companies shortlisted. The point of a shortlist is to be short — "
            "two to five is the useful range for a side-by-side comparison.",
        )
    elif len(shortlist) < 2:
        st.caption("Add at least one more company to make the comparison useful.")

    cols = st.columns(min(len(shortlist), 5))
    for col, startup in zip(cols, shortlist[:5]):
        with col:
            recommendation, _ = decide_recommendation(startup)
            st.metric(
                startup.display_name,
                f"{startup.score_total:.0f}/100" if startup.score_total is not None else "—",
                help=startup.product_summary or "",
            )
            st.caption(recommendation.label)
            if st.button("Remove", key=f"rm_{startup.id}", width="stretch"):
                state.repo().remove_from_shortlist(startup.id)
                st.rerun()

    provenance_panel(shortlist, state.evidence(), key_prefix="short_")

    theme.rule()
    st.markdown("### How the pipeline narrowed")
    funnel_chart(state.startups(), len(shortlist), key="funnel_shortlist")

    theme.rule()
    st.markdown("### Side-by-side comparison")
    st.dataframe(comparison_frame(shortlist), hide_index=True, width="stretch")

    theme.rule()
    st.markdown("### Why each of these is worth investigating")
    for startup in shortlist:
        recommendation, reason = decide_recommendation(startup)
        with st.expander(f"{startup.display_name} — {recommendation.label}", expanded=True):
            st.caption(reason)
            if startup.product_summary:
                st.markdown(f"**What they do.** {startup.product_summary}")
            if startup.why_now_signal:
                st.markdown(f"**Why now.** {startup.why_now_signal}")
            if startup.technical_moat:
                st.markdown(f"**Differentiation.** {startup.technical_moat}")
            open_q = startup.open_questions[:3]
            if open_q:
                st.markdown("**Still to answer:**")
                for question in open_q:
                    st.markdown(f"- {question}")
            if startup.source_urls:
                st.markdown("**Sources:** " + " · ".join(
                    f"[{url.split('//')[-1][:40]}]({url})" for url in startup.source_urls[:5]
                ))

    theme.rule()
    st.markdown("### Export")
    export = export_frame(shortlist)
    cols = st.columns(2)
    cols[0].download_button(
        "Shortlist as CSV",
        export.to_csv(index=False),
        f"final_shortlist_{state.dataset().value.lower()}.csv",
        "text/csv",
        width="stretch",
    )

    if cols[1].button("Build memos and Loom scripts for all", width="stretch"):
        bundle: list[str] = []
        progress = st.progress(0.0)
        for index, startup in enumerate(shortlist, 1):
            memo = generate_memo(startup, state.thesis(), state.evidence(), state.analyst())
            pitch = generate_loom_script(
                startup, state.thesis(), state.evidence(), state.analyst(), memo.to_markdown()
            )
            st.session_state.memo_cache[startup.id] = memo
            st.session_state.loom_cache[startup.id] = pitch
            bundle.append(memo.to_markdown())
            bundle.append("\n\n---\n\n")
            bundle.append(pitch.to_markdown())
            bundle.append("\n\n===\n\n")
            progress.progress(index / len(shortlist))
        progress.empty()
        st.session_state["shortlist_bundle"] = "".join(bundle)
        st.success("Memos and scripts generated for the whole shortlist.")

    if st.session_state.get("shortlist_bundle"):
        st.download_button(
            "Download all memos and scripts (Markdown)",
            st.session_state["shortlist_bundle"],
            f"shortlist_pack_{state.dataset().value.lower()}.md",
            "text/markdown",
            width="stretch",
        )
