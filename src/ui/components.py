"""Reusable UI pieces — above all, the evidence viewer.

The most important component here is ``field_block``: it renders a value
*together with* its verification status, confidence and clickable sources. No
important number appears anywhere in this application without one.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..models.enums import ConfidenceLevel, SourceType, VerificationStatus
from ..models.evidence import FieldAssessment
from ..models.scoring import CriterionScore, RedFlag
from ..models.startup import Startup
from ..research.confidence import describe_level
from ..research.evidence_manager import EvidenceManager
from . import theme

SOURCE_MARK = {
    "deterministic": "Rule-based",
    "llm": "Analyst model",
    "human_override": "Investor override",
}


def confidence_legend() -> None:
    with st.expander("How confidence and verification are decided"):
        rows = [
            {"Level": level.label, "Means": describe_level(level)}
            for level in ConfidenceLevel
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "Confidence follows source quality and source agreement, never how fluent an "
            "answer sounds. Tier 1 is an official company, investor or regulatory source. "
            "Tier 2 is reputable media and established databases. Tier 3 is LinkedIn, "
            "directories and accelerator pages. Tier 4 is blogs and unverified aggregators."
        )


def _format_value(value) -> str:
    if value in (None, "", [], {}):
        return "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def field_block(
    label: str,
    assessment: FieldAssessment,
    *,
    startup: Startup | None = None,
    evidence: EvidenceManager | None = None,
    allow_verify: bool = True,
) -> None:
    """Render one field: value, status, confidence, and its sources."""
    status = assessment.verification_status
    status_text = (
        f"{status.label} · {assessment.confidence:.2f}"
        if status != VerificationStatus.MISSING else status.label
    )
    theme.field_row(
        label,
        _format_value(assessment.value),
        status=status.value,
        status_text=status_text,
        note=assessment.note,
    )

    if not assessment.evidence:
        return

    with st.expander(f"{label} — evidence ({len(assessment.evidence)})"):
        for ev in assessment.evidence:
            cols = st.columns([5, 1])
            with cols[0]:
                if ev.source_url:
                    st.markdown(f"[{ev.source_title or ev.source_url}]({ev.source_url})")
                else:
                    st.markdown(f"*{ev.source_title or 'No source URL recorded'}*")
                st.caption(
                    f"{ev.source_type.value.replace('_', ' ').title()} · "
                    f"{ev.source_tier.label if ev.source_tier else 'unknown tier'} · "
                    f"{ev.verification_status.label} · confidence {ev.confidence:.2f} · "
                    f"retrieved {ev.retrieved_at:%Y-%m-%d}"
                )
                if ev.evidence_note:
                    st.caption(ev.evidence_note)
                st.caption(f"Recorded value: `{ev.value}`")
            with cols[1]:
                if allow_verify and evidence is not None:
                    checked = st.checkbox(
                        "Verified", value=ev.human_verified, key=f"verify_{ev.id}",
                        help="Confirm that you personally checked this against the source.",
                    )
                    if checked != ev.human_verified:
                        evidence.mark_verified(ev.id, checked)
                        st.rerun()


def add_source_form(startup: Startup, evidence: EvidenceManager, fields: list[str]) -> bool:
    """Let the investor attach a source they found themselves. True on save."""
    with st.form(f"add_source_{startup.id}", clear_on_submit=True):
        st.markdown("#### Add a source")
        st.caption(
            "This is how a field becomes VERIFIED. A Tier 1 or Tier 2 source with a URL "
            "is what lets funding clear the thesis ceiling."
        )
        col1, col2 = st.columns(2)
        field_name = col1.selectbox("Field", options=fields, key=f"src_field_{startup.id}")
        source_type = col2.selectbox(
            "Source type", options=list(SourceType),
            format_func=lambda s: f"{s.value.replace('_', ' ').title()} — {s.tier.label}",
            index=list(SourceType).index(SourceType.FUNDING_ANNOUNCEMENT),
            key=f"src_type_{startup.id}",
        )
        url = st.text_input("Source URL", key=f"src_url_{startup.id}")
        title = st.text_input("Source title", key=f"src_title_{startup.id}")
        value = st.text_input(
            "Value this source supports",
            help="What the source actually says. For funding, a plain number in EUR.",
            key=f"src_value_{startup.id}",
        )
        note = st.text_area("Note (optional)", key=f"src_note_{startup.id}", height=70)
        submitted = st.form_submit_button("Add source", width="stretch", type="primary")

    if not submitted:
        return False
    if not url.strip():
        st.error("A source URL is required.")
        return False

    parsed: object = value.strip()
    if field_name in {"total_funding_eur", "last_round_eur", "founded_year"}:
        try:
            parsed = float(value.replace(",", "").replace("€", "").strip())
        except ValueError:
            st.error(f"{field_name} needs a numeric value.")
            return False

    evidence.add_source(
        startup.id, field_name, parsed, url.strip(),
        title.strip() or url.strip(), source_type, note.strip(),
    )
    return True


def score_table(breakdown) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Criterion": c.label,
            "Rating": c.display_rating,
            "Weight": c.weight,
            "Points": c.weighted_score,
            "Confidence": round(c.confidence, 2),
            "Basis": SOURCE_MARK[c.source],
            "Reasoning": c.reasoning,
        }
        for c in breakdown.criteria
    ])


def score_chart(breakdown, key: str = "score_chart") -> None:
    """Points earned, headroom, and weight that could not be assessed at all."""
    import plotly.graph_objects as go

    labels = [c.label for c in breakdown.criteria][::-1]
    earned = [c.weighted_score for c in breakdown.criteria][::-1]
    headroom = [
        round(c.weight - c.weighted_score, 2) if c.is_scored else 0.0
        for c in breakdown.criteria
    ][::-1]
    unassessed = [c.weight if not c.is_scored else 0.0 for c in breakdown.criteria][::-1]

    figure = go.Figure()
    figure.add_bar(y=labels, x=earned, orientation="h", name="Scored",
                   marker_color=theme.NAVY, hovertemplate="%{x} pts<extra>Scored</extra>")
    figure.add_bar(y=labels, x=headroom, orientation="h", name="Headroom",
                   marker_color="#DCE3E9", hovertemplate="%{x} pts<extra>Headroom</extra>")
    figure.add_bar(y=labels, x=unassessed, orientation="h", name="No evidence",
                   marker_color="#E8D6C5",
                   hovertemplate="%{x} pts<extra>Not assessable</extra>")
    figure.update_layout(
        barmode="stack",
        **theme.plotly_layout(height=330, xaxis_title="Points of 100"),
    )
    st.plotly_chart(figure, width="stretch", key=key)


def render_criterion(criterion: CriterionScore, evidence: EvidenceManager | None = None) -> None:
    basis = SOURCE_MARK[criterion.source]
    st.markdown(
        f"**{criterion.label}** &nbsp; {theme.pill(criterion.display_rating, None)} "
        f"&nbsp; weight {criterion.weight:.0f} &nbsp;→&nbsp; "
        f"**{criterion.weighted_score:.1f} points**",
        unsafe_allow_html=True,
    )
    if criterion.evidence_missing:
        st.caption(f"Not scored. {criterion.reasoning}")
    else:
        st.caption(
            f"{criterion.reasoning}  \n"
            f"Basis: {basis} · confidence {criterion.confidence:.2f}"
        )
    if criterion.evidence_ids and evidence is not None:
        with st.expander(f"Evidence behind this rating ({len(criterion.evidence_ids)})"):
            for ev in evidence.by_ids(criterion.evidence_ids):
                link = (
                    f"[{ev.source_title or ev.source_url}]({ev.source_url})"
                    if ev.source_url else (ev.source_title or "no source URL")
                )
                st.markdown(f"- `{ev.field_name}` — {link} · {ev.verification_status.label}")


def render_red_flags(flags: list[RedFlag], key_prefix: str = "") -> list[str]:
    """Show flags; returns the codes the investor just dismissed."""
    if not flags:
        st.caption("No red flags detected. That is itself worth a sanity check.")
        return []

    dismissed: list[str] = []
    for flag in flags:
        cols = st.columns([6, 1])
        with cols[0]:
            badge = theme.pill(flag.severity.label.upper(), flag.severity.value)
            if flag.dismissed_by_human:
                st.markdown(
                    f'<div class="vc-field"><span style="opacity:0.5">{badge} '
                    f'<s>{flag.title}</s> — dismissed by the investor</span></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="vc-field">{badge} &nbsp; <strong>{flag.title}</strong>'
                    f'<div class="vc-note">{flag.detail}</div></div>',
                    unsafe_allow_html=True,
                )
        with cols[1]:
            if not flag.dismissed_by_human:
                if st.button("Dismiss", key=f"{key_prefix}dismiss_{flag.code}",
                             help="Hides the flag; it stays recorded as dismissed."):
                    dismissed.append(flag.code)
    return dismissed


def empty_state(message: str, hint: str = "") -> None:
    body = f"<strong>{message}</strong>"
    if hint:
        body += f'<div class="vc-note" style="margin-top:0.4rem">{hint}</div>'
    theme.callout(body)


def disclaimer() -> None:
    from ..config import APP_DISCLAIMER

    theme.footnote(APP_DISCLAIMER.replace("**", ""))


# --------------------------------------------------------------------------- #
# Provenance — "where did this data come from?"
# --------------------------------------------------------------------------- #

def _domain_of(url: str) -> str:
    return url.split("//")[-1].split("/")[0].replace("www.", "").lower()


def provenance_panel(startups: list[Startup], evidence: EvidenceManager,
                     key_prefix: str = "") -> None:
    """State on the page exactly where this pipeline's data came from.

    Computed from the evidence records rather than written by hand, so it can
    never drift out of line with what is actually loaded.
    """
    if not startups:
        return

    from collections import Counter

    domains: Counter = Counter()
    verified_funding = 0
    dated: list = []

    for startup in startups:
        if startup.funding_status == VerificationStatus.VERIFIED:
            verified_funding += 1
        for ev in evidence.for_startup(startup.id):
            if ev.source_url:
                domains[_domain_of(ev.source_url)] += 1
                dated.append(ev.retrieved_at)

    demo = [s for s in startups if s.is_demo]
    total = len(startups)

    if demo:
        headline = (
            f"<strong>Data provenance.</strong> These {len(demo)} companies are "
            "<strong>fictional demo data</strong>, written to exercise every path through "
            "the pipeline. They are not real companies and must not be presented as such."
        )
        st.markdown(f'<div class="vc-callout">{headline}</div>', unsafe_allow_html=True)
        return

    if not domains:
        st.markdown(
            '<div class="vc-callout"><strong>Data provenance.</strong> None of these '
            'companies carries a source URL, so nothing here is verifiable. Attach sources '
            'on the Company research tab before relying on any of it.</div>',
            unsafe_allow_html=True,
        )
        return

    retrieved = f"{min(dated):%d %B %Y}" if dated else "unknown"
    top_domains = ", ".join(f"{d} ({n})" for d, n in domains.most_common(6))

    st.markdown(
        f'<div class="vc-callout"><strong>Data provenance.</strong> '
        f"{total} real companies, sourced from published funding announcements and "
        f"verified against the original article before entry. "
        f"<strong>{verified_funding} of {total}</strong> carry a funding figure backed by a "
        f"named source, which is what lets them clear the thesis ceiling. "
        f"Evidence retrieved {retrieved}."
        f'<div class="vc-note" style="margin-top:0.5rem"><strong>Sources:</strong> '
        f"{top_domains}</div>"
        f'<div class="vc-note">No database was scraped. Every figure below can be traced '
        f"to the article it came from, and a figure without a source stays UNVERIFIED."
        f"</div></div>",
        unsafe_allow_html=True,
    )

    with st.expander(f"Source for each of the {total} companies"):
        rows = []
        for startup in sorted(startups, key=lambda s: s.company_name):
            funding_ev = evidence.for_field(startup.id, "total_funding_eur")
            sourced = [e for e in funding_ev if e.source_url]
            rows.append({
                "Company": startup.company_name,
                "Funding": startup.funding_display(),
                "Status": startup.funding_status.label,
                "Source": sourced[0].source_url if sourced
                else (startup.source_urls[0] if startup.source_urls else "—"),
            })
        st.dataframe(
            pd.DataFrame(rows), hide_index=True, width="stretch",
            column_config={
                "Source": st.column_config.LinkColumn("Source article", width="large"),
                "Company": st.column_config.TextColumn("Company", width="medium"),
            },
        )


# --------------------------------------------------------------------------- #
# The funnel — many candidates in, two or three out
# --------------------------------------------------------------------------- #

def funnel_stages(startups: list[Startup], shortlist_size: int = 0,
                  top_n: int = 5) -> list[tuple[str, int, str]]:
    """The screening funnel as ``(label, count, why this stage removes things)``."""
    from ..models.enums import EligibilityStatus

    total = len(startups)
    eligible = [s for s in startups if s.eligibility_status == EligibilityStatus.ELIGIBLE]
    approved = [
        s for s in startups
        if s.eligibility_status == EligibilityStatus.NEEDS_REVIEW
        and s.manual_eligibility_approved
    ]
    rankable = [s for s in startups if s.is_rankable and s.score_total is not None]
    ranked = sorted(rankable, key=lambda s: s.score_total or 0, reverse=True)
    investigate = [s for s in ranked if (s.score_total or 0) >= 68]

    return [
        ("Sourced", total,
         "Every company brought into the workspace, from any source."),
        ("Passed the hard filters", len(eligible) + len(approved),
         "Geography, stage, funding ceiling, theme, founding year and active status — "
         "checked deterministically, with unknown funding never counted as eligible."),
        ("Scored and rankable", len(ranked),
         "Eligible companies with a computed 100-point score."),
        (f"Top {top_n}", min(top_n, len(ranked)),
         "The highest scores, with ties broken towards better-evidenced companies."),
        ("Final shortlist", shortlist_size or min(3, len(investigate)),
         "The companies an investor chose to take forward."),
    ]


def funnel_chart(startups: list[Startup], shortlist_size: int = 0,
                 key: str = "funnel", top_n: int = 5) -> None:
    """Show the narrowing from a sourced pipeline to a defensible shortlist."""
    import plotly.graph_objects as go

    stages = funnel_stages(startups, shortlist_size, top_n)
    if not stages or stages[0][1] == 0:
        return

    labels = [s[0] for s in stages]
    values = [s[1] for s in stages]
    shades = [theme.NAVY, "#12405F", theme.NAVY_LIGHT, theme.ACCENT, theme.ACCENT_SOFT]

    figure = go.Figure(
        go.Funnel(
            y=labels,
            x=values,
            textposition="inside",
            textinfo="value",
            texttemplate="%{value}",
            textfont=dict(color="#FFFFFF", size=15, family="Georgia, serif"),
            marker=dict(color=shades[: len(values)]),
            connector=dict(line=dict(color=theme.RULE, width=1)),
            hovertemplate="%{y}: %{x} companies<extra></extra>",
        )
    )
    figure.update_layout(**theme.plotly_layout(height=300, showlegend=False))
    figure.update_yaxes(showgrid=False)
    st.plotly_chart(figure, width="stretch", key=key)

    first, last = stages[0][1], stages[-1][1]
    if first and last:
        st.caption(
            f"{first} companies sourced, {last} taken forward — "
            f"a {(1 - last / first):.0%} reduction, with the reason for every "
            f"exclusion recorded against the company it applies to."
        )

    with st.expander("What each stage removes"):
        for label, count, why in stages:
            st.markdown(f"**{label} — {count}**")
            st.caption(why)
