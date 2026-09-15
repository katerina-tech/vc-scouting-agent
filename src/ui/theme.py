"""The visual design system.

A restrained consulting-report aesthetic: deep navy, a single accent, generous
whitespace, serif display headings over a sans body, thin rules instead of
boxes, and no decorative colour. Colour is reserved for data and for status.

Everything is defined once here as CSS custom properties so the whole
application stays visually consistent, and so a palette change is a one-file
edit rather than a hunt through eight page modules.
"""

from __future__ import annotations

import streamlit as st

# --------------------------------------------------------------------------- #
# Palette
# --------------------------------------------------------------------------- #

NAVY = "#051C2C"        # primary — headings, sidebar, chart ink
NAVY_MID = "#0A3A5C"
NAVY_LIGHT = "#1B6091"
ACCENT = "#2B6CB0"      # the single accent, used for data and emphasis
ACCENT_SOFT = "#8AB4D8"

INK = "#1A1A1A"
INK_MUTED = "#5A6472"
RULE = "#D9DEE4"
CANVAS = "#FFFFFF"
CANVAS_ALT = "#F5F7F9"

POSITIVE = "#1B6E4F"
CAUTION = "#8A6100"
NEGATIVE = "#A32B2B"
NEUTRAL = "#6B7684"

#: Ordered categorical palette for charts. Sequential navy-to-accent ramp,
#: deliberately narrow so a chart never looks like a pie of confetti.
CHART_SEQUENCE = [NAVY, ACCENT, NAVY_LIGHT, ACCENT_SOFT, "#4A5568", "#A0AEC0"]

STATUS_COLOURS = {
    "VERIFIED": POSITIVE,
    "INFERRED": CAUTION,
    "UNVERIFIED": NEGATIVE,
    "MISSING": NEUTRAL,
    "ELIGIBLE": POSITIVE,
    "NEEDS_REVIEW": CAUTION,
    "INELIGIBLE": NEGATIVE,
    "NOT_ASSESSED": NEUTRAL,
    "HIGH": POSITIVE,
    "MEDIUM": CAUTION,
    "LOW": CAUTION,
    "INFO": NEUTRAL,
    "INVESTIGATE": POSITIVE,
    "WATCH": CAUTION,
    "PASS": NEUTRAL,
}


CSS = f"""
<style>
:root {{
    --navy: {NAVY};
    --navy-mid: {NAVY_MID};
    --navy-light: {NAVY_LIGHT};
    --accent: {ACCENT};
    --accent-soft: {ACCENT_SOFT};
    --ink: {INK};
    --ink-muted: {INK_MUTED};
    --rule: {RULE};
    --canvas: {CANVAS};
    --canvas-alt: {CANVAS_ALT};
    --positive: {POSITIVE};
    --caution: {CAUTION};
    --negative: {NEGATIVE};
    --neutral: {NEUTRAL};
    --serif: Georgia, "Times New Roman", "Iowan Old Style", serif;
    --sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
}}

/* ---------- canvas ---------- */
.stApp {{ background: var(--canvas); }}
.block-container {{
    padding-top: 2.25rem;
    padding-bottom: 5rem;
    max-width: 1320px;
}}
html, body, [class*="st-"], .stMarkdown, p, li, td, th, label, input, textarea, select {{
    font-family: var(--sans);
    color: var(--ink);
}}
p, li {{ line-height: 1.6; }}

/* ---------- display typography ---------- */
h1, h2, h3 {{
    font-family: var(--serif) !important;
    color: var(--navy) !important;
    letter-spacing: -0.01em;
    font-weight: 600 !important;
}}
h1 {{ font-size: 2.1rem !important; line-height: 1.2; margin-bottom: 0.25rem !important; }}
h2 {{ font-size: 1.45rem !important; margin-top: 2.2rem !important; }}
h3 {{ font-size: 1.15rem !important; margin-top: 1.6rem !important; }}
h4, h5, h6 {{
    font-family: var(--sans) !important;
    color: var(--navy) !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    margin-top: 1.5rem !important;
    margin-bottom: 0.4rem !important;
}}

/* ---------- masthead ---------- */
.vc-masthead {{
    border-bottom: 2px solid var(--navy);
    padding-bottom: 0.9rem;
    margin-bottom: 0.4rem;
}}
.vc-masthead .vc-title {{
    font-family: var(--serif);
    font-size: 1.35rem;
    font-weight: 600;
    color: var(--navy);
    letter-spacing: -0.01em;
}}
.vc-masthead .vc-sub {{
    font-size: 0.8rem;
    color: var(--ink-muted);
    margin-top: 0.15rem;
}}

/* ---------- eyebrow / lede ---------- */
.vc-eyebrow {{
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 0.68rem;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 0.35rem;
}}
.vc-lede {{
    font-size: 0.98rem;
    color: var(--ink-muted);
    max-width: 72ch;
    line-height: 1.6;
    margin-bottom: 0.5rem;
}}
.vc-rule {{
    border: none;
    border-top: 1px solid var(--rule);
    margin: 1.6rem 0 1.2rem 0;
}}

/* ---------- tabs as a top navigation bar ---------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0;
    border-bottom: 1px solid var(--rule);
    background: transparent;
}}
.stTabs [data-baseweb="tab"] {{
    height: 44px;
    padding: 0 1.15rem;
    background: transparent;
    border-radius: 0;
    font-size: 0.83rem;
    font-weight: 600;
    letter-spacing: 0.02em;
    color: var(--ink-muted);
}}
.stTabs [aria-selected="true"] {{
    color: var(--navy) !important;
    border-bottom: 2px solid var(--accent);
}}
.stTabs [data-baseweb="tab-highlight"] {{ display: none; }}

/* ---------- metrics ---------- */
[data-testid="stMetric"] {{
    background: var(--canvas-alt);
    border-left: 3px solid var(--navy);
    padding: 0.85rem 1rem;
}}
[data-testid="stMetricLabel"] p {{
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-size: 0.66rem !important;
    font-weight: 700;
    color: var(--ink-muted) !important;
}}
[data-testid="stMetricValue"] {{
    font-family: var(--serif);
    font-size: 1.7rem !important;
    color: var(--navy) !important;
    font-weight: 600;
}}

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
    border-radius: 2px;
    border: 1px solid var(--rule);
    background: var(--canvas);
    color: var(--navy);
    font-weight: 600;
    font-size: 0.82rem;
    letter-spacing: 0.01em;
    padding: 0.45rem 1rem;
    transition: background 120ms ease, border-color 120ms ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
    border-color: var(--navy);
    background: var(--canvas-alt);
    color: var(--navy);
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
    background: var(--navy);
    border-color: var(--navy);
    color: #FFFFFF;
}}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {{
    background: var(--navy-mid);
    border-color: var(--navy-mid);
    color: #FFFFFF;
}}

/* ---------- inputs ---------- */
.stTextInput input, .stNumberInput input, .stTextArea textarea,
[data-baseweb="select"] > div {{
    border-radius: 2px !important;
    border-color: var(--rule) !important;
    font-size: 0.86rem;
}}
[data-baseweb="tag"] {{
    background: var(--navy) !important;
    border-radius: 2px !important;
    font-size: 0.74rem !important;
}}

/* ---------- expanders and containers ---------- */
[data-testid="stExpander"] {{
    border: 1px solid var(--rule);
    border-radius: 2px;
    background: var(--canvas);
}}
[data-testid="stExpander"] summary {{
    font-size: 0.83rem;
    font-weight: 600;
    color: var(--navy);
}}
[data-testid="stExpander"] summary p {{ font-weight: 600; }}

/* ---------- icon-font fallback ----------
   Streamlit draws its icons with Material Symbols, fetched from Google Fonts.
   When that request is blocked — a corporate proxy, an offline machine, an
   application-control policy — the browser has no glyph for the ligature and
   paints the ligature's NAME instead, so "keyboard_arrow_right" lands on top
   of the label next to it. Collapsing the text to zero size removes the
   collision whether or not the font ever arrives; expanders then get a
   chevron drawn from a character every system font already has. */
[data-testid="stIconMaterial"] {{
    font-size: 0 !important;
    line-height: 0 !important;
    letter-spacing: 0 !important;
    overflow: hidden;
}}
[data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{
    width: 1rem;
    display: inline-flex;
    justify-content: center;
}}
[data-testid="stExpander"] summary [data-testid="stIconMaterial"]::after {{
    content: "\\203A";                       /* › — present in every system font */
    font-family: var(--sans);
    font-size: 1.05rem;
    line-height: 1;
    font-weight: 700;
    color: var(--ink-muted);
    display: inline-block;
    transition: transform 140ms ease;
}}
[data-testid="stExpander"] details[open] summary [data-testid="stIconMaterial"]::after {{
    transform: rotate(90deg);
}}
details[open] > summary [data-testid="stIconMaterial"]::after {{
    transform: rotate(90deg);
}}

/* ---------- tables ---------- */
[data-testid="stDataFrame"] {{
    border: 1px solid var(--rule);
    border-radius: 2px;
}}

/* ---------- alerts: flat, left-ruled, no fill shouting ---------- */
[data-testid="stAlert"],
[data-testid="stAlertContainer"],
[data-testid="stNotification"],
div[role="alert"] {{
    border-radius: 2px !important;
    border: 1px solid var(--rule) !important;
    border-left: 3px solid var(--neutral) !important;
    background: var(--canvas-alt) !important;
    padding: 0.7rem 0.9rem;
    color: var(--ink) !important;
}}
[data-testid="stAlert"] p,
[data-testid="stAlertContainer"] p,
div[role="alert"] p {{ font-size: 0.85rem; color: var(--ink) !important; }}
[data-testid="stAlertContainer"] svg, [data-testid="stAlert"] svg {{ display: none; }}

/* success / warning / error get their own left rule, nothing more */
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]),
div[role="alert"]:has(.stAlertContentSuccess) {{ border-left-color: var(--positive) !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
    border-left-color: var(--caution) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{
    border-left-color: var(--negative) !important;
}}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
    border-left-color: var(--accent) !important;
}}

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] {{
    background: var(--navy);
    border-right: none;
}}
[data-testid="stSidebar"] * {{ color: #E6ECF2 !important; }}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] h4 {{
    color: #FFFFFF !important;
}}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.15); }}
[data-testid="stSidebar"] .stButton > button {{
    background: transparent;
    border-color: rgba(255,255,255,0.3);
    color: #E6ECF2;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(255,255,255,0.08);
    border-color: #FFFFFF;
}}
[data-testid="stSidebar"] [data-testid="stAlert"] {{
    background: rgba(255,255,255,0.07);
    border-color: rgba(255,255,255,0.2);
}}

/* ---------- custom components ---------- */
.vc-pill {{
    display: inline-block;
    padding: 0.12rem 0.5rem;
    border-radius: 2px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    border: 1px solid currentColor;
    white-space: nowrap;
}}
.vc-field {{
    padding: 0.7rem 0;
    border-bottom: 1px solid var(--rule);
}}
.vc-field-label {{
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-size: 0.66rem;
    font-weight: 700;
    color: var(--ink-muted);
    margin-bottom: 0.2rem;
}}
.vc-field-value {{ font-size: 0.92rem; color: var(--ink); }}
.vc-field-value.vc-empty {{ color: var(--neutral); font-style: italic; }}
.vc-note {{ font-size: 0.76rem; color: var(--ink-muted); margin-top: 0.25rem; }}

.vc-callout {{
    border-left: 3px solid var(--accent);
    background: var(--canvas-alt);
    padding: 0.85rem 1rem;
    margin: 0.8rem 0;
    font-size: 0.87rem;
}}
.vc-callout strong {{ color: var(--navy); }}

.vc-source-card {{
    border: 1px solid var(--rule);
    border-top: 3px solid var(--navy);
    padding: 1rem 1.1rem;
    margin-bottom: 0.9rem;
    background: var(--canvas);
}}
.vc-source-card h5 {{ margin-top: 0 !important; }}

.vc-demo-banner {{
    background: repeating-linear-gradient(
        45deg, {CANVAS_ALT}, {CANVAS_ALT} 10px, #EEF1F4 10px, #EEF1F4 20px
    );
    border-left: 3px solid var(--caution);
    padding: 0.6rem 0.9rem;
    font-size: 0.8rem;
    color: var(--ink-muted);
    margin-bottom: 1rem;
}}

.vc-footnote {{
    font-size: 0.72rem;
    color: var(--ink-muted);
    border-top: 1px solid var(--rule);
    padding-top: 0.6rem;
    margin-top: 2rem;
}}

/* hide Streamlit chrome that breaks the report feel */
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stDecoration"] {{ display: none; }}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #

def masthead(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="vc-masthead"><div class="vc-title">{title}</div>'
        f'<div class="vc-sub">{subtitle}</div></div>',
        unsafe_allow_html=True,
    )


def page_header(eyebrow: str, title: str, lede: str = "") -> None:
    st.markdown(f'<div class="vc-eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.markdown(f"# {title}")
    if lede:
        st.markdown(f'<div class="vc-lede">{lede}</div>', unsafe_allow_html=True)


def rule() -> None:
    st.markdown('<hr class="vc-rule">', unsafe_allow_html=True)


def pill(text: str, status: str | None = None) -> str:
    colour = STATUS_COLOURS.get(status or "", NEUTRAL)
    return f'<span class="vc-pill" style="color:{colour}">{text}</span>'


def callout(body: str) -> None:
    st.markdown(f'<div class="vc-callout">{body}</div>', unsafe_allow_html=True)


def demo_banner(text: str) -> None:
    st.markdown(f'<div class="vc-demo-banner">{text}</div>', unsafe_allow_html=True)


def footnote(text: str) -> None:
    st.markdown(f'<div class="vc-footnote">{text}</div>', unsafe_allow_html=True)


def field_row(label: str, value: str, status: str | None = None,
              status_text: str = "", note: str = "") -> None:
    empty = "" if value and value != "—" else " vc-empty"
    badge = f" &nbsp; {pill(status_text, status)}" if status_text else ""
    note_html = f'<div class="vc-note">{note}</div>' if note else ""
    st.markdown(
        f'<div class="vc-field"><div class="vc-field-label">{label}</div>'
        f'<div class="vc-field-value{empty}">{value}{badge}</div>{note_html}</div>',
        unsafe_allow_html=True,
    )


def plotly_layout(height: int = 320, **overrides) -> dict:
    """A consistent, quiet chart layout: no gridlines shouting, navy ink."""
    layout = dict(
        height=height,
        margin=dict(l=8, r=8, t=28, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="-apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
            size=12,
            color=INK,
        ),
        xaxis=dict(gridcolor=RULE, zerolinecolor=RULE, linecolor=RULE, tickfont=dict(size=11)),
        yaxis=dict(gridcolor="rgba(0,0,0,0)", linecolor=RULE, tickfont=dict(size=11)),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    font=dict(size=11), bgcolor="rgba(0,0,0,0)"),
        colorway=CHART_SEQUENCE,
        hoverlabel=dict(bgcolor=NAVY, font=dict(color="#FFFFFF", size=11)),
    )
    layout.update(overrides)
    return layout
