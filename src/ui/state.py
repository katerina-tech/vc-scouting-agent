"""Session state, cached resources, and the shared sidebar.

Streamlit reruns the whole script on every interaction, so anything expensive or
stateful (the database connection, the evidence index, the thesis) lives here
behind ``st.session_state``.
"""

from __future__ import annotations

import streamlit as st

from ..config import APP_NAME, APP_VERSION, get_llm_settings
from ..llm.client import estimate_cost_usd, get_llm_client
from ..llm.investment_analyst import InvestmentAnalyst
from ..models.enums import Dataset
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..pipeline import load_workspace
from ..research.evidence_manager import EvidenceManager
from ..storage.repository import Repository

DEMO_BANNER = (
    "DEMO DATASET — every company shown is fictional and exists only to exercise the "
    "pipeline. Demo and real companies are stored separately and never mixed."
)


def init_state() -> None:
    """Create everything the app needs exactly once per session."""
    if "repo" not in st.session_state:
        st.session_state.repo = Repository()
    if "dataset" not in st.session_state:
        # Open on whichever pool actually has companies in it, so a returning
        # session never lands on an empty screen. Real work wins a tie.
        repository = st.session_state.repo
        if repository.count(Dataset.REAL):
            st.session_state.dataset = Dataset.REAL
        elif repository.count(Dataset.DEMO):
            st.session_state.dataset = Dataset.DEMO
        else:
            st.session_state.dataset = Dataset.REAL
    if "thesis" not in st.session_state:
        saved = st.session_state.repo.load_thesis()
        st.session_state.thesis = saved or InvestmentThesis()
    if "evidence" not in st.session_state:
        _, manager = load_workspace(st.session_state.repo, st.session_state.dataset)
        st.session_state.evidence = manager
    if "analyst" not in st.session_state:
        st.session_state.analyst = InvestmentAnalyst(get_llm_client())
    if "selected_startup_id" not in st.session_state:
        st.session_state.selected_startup_id = None
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "memo_cache" not in st.session_state:
        st.session_state.memo_cache = {}
    if "loom_cache" not in st.session_state:
        st.session_state.loom_cache = {}


# ------------------------------------------------------------------ accessors
def repo() -> Repository:
    return st.session_state.repo


def evidence() -> EvidenceManager:
    return st.session_state.evidence


def thesis() -> InvestmentThesis:
    return st.session_state.thesis


def analyst() -> InvestmentAnalyst:
    return st.session_state.analyst


def dataset() -> Dataset:
    return st.session_state.dataset


def startups() -> list[Startup]:
    return repo().list_startups(dataset())


def selected_startup() -> Startup | None:
    startup_id = st.session_state.get("selected_startup_id")
    return repo().get_startup(startup_id) if startup_id else None


def select_startup(startup_id: str | None) -> None:
    st.session_state.selected_startup_id = startup_id


def set_thesis(new_thesis: InvestmentThesis) -> None:
    st.session_state.thesis = new_thesis
    repo().save_thesis(new_thesis)


def set_dataset(new_dataset: Dataset) -> None:
    if new_dataset == st.session_state.dataset:
        return
    st.session_state.dataset = new_dataset
    st.session_state.selected_startup_id = None
    st.session_state.memo_cache = {}
    st.session_state.loom_cache = {}
    _, manager = load_workspace(repo(), new_dataset)
    st.session_state.evidence = manager


def reload_evidence() -> None:
    _, manager = load_workspace(repo(), dataset())
    st.session_state.evidence = manager


def flash(message: str, kind: str = "info") -> None:
    st.session_state.messages.append((kind, message))


def drain_messages() -> None:
    for kind, message in st.session_state.messages:
        getattr(st, kind, st.info)(message)
    st.session_state.messages = []


# --------------------------------------------------------------------- chrome
def render_sidebar() -> None:
    """The persistent left rail: dataset switch, thesis summary, LLM status."""
    with st.sidebar:
        st.markdown(
            f'<div style="font-family:Georgia,serif;font-size:1.05rem;font-weight:600;'
            f'letter-spacing:-0.01em;line-height:1.25">{APP_NAME}</div>'
            f'<div style="font-size:0.68rem;letter-spacing:0.1em;text-transform:uppercase;'
            f'opacity:0.65;margin-top:0.3rem">Version {APP_VERSION}</div>',
            unsafe_allow_html=True,
        )

        st.divider()
        st.markdown("#### Dataset")
        current = dataset()
        choice = st.radio(
            "Dataset",
            options=[Dataset.DEMO, Dataset.REAL],
            format_func=lambda d: d.label,
            index=0 if current == Dataset.DEMO else 1,
            key="dataset_radio",
            label_visibility="collapsed",
            help="Demo and real companies are stored separately and can never be mixed.",
        )
        if choice != current:
            set_dataset(choice)
            st.rerun()

        st.divider()
        st.markdown("#### Thesis in force")
        st.caption(thesis().summary())

        st.divider()
        st.markdown("#### Analyst model")
        settings = get_llm_settings()
        client = analyst()
        if client.available:
            st.caption(client.describe())
            usage = client.usage
            if usage.calls:
                cost = estimate_cost_usd(settings.model, usage)
                st.caption(
                    f"{usage.calls} call(s) · {usage.total_tokens:,} tokens"
                    + (f" · approx. ${cost:.4f}" if cost is not None else "")
                )
        else:
            st.caption(client.describe())
            st.caption(
                "Scoring, eligibility, memos and Loom scripts all have deterministic "
                "implementations, so nothing depends on a model being configured."
            )

        st.divider()
        stats = repo().stats()
        st.markdown("#### Workspace")
        st.caption(
            f"{stats['real_companies']} real · {stats['demo_companies']} demo · "
            f"{stats['evidence']} evidence records · {stats['shortlisted']} shortlisted"
        )

        with st.expander("Reset workspace"):
            st.caption("Clears every company in the current dataset. Cannot be undone.")
            if st.button(f"Clear the {current.value.lower()} dataset", width="stretch"):
                removed = repo().clear_dataset(current)
                reload_evidence()
                select_startup(None)
                flash(f"Removed {removed} companies from the {current.value} dataset.", "warning")
                st.rerun()
