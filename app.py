"""VC Startup Scouting Agent — Streamlit entry point.

Deliberately thin. All logic lives in ``src/``; the pages live in ``src/ui/``.

    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from src.config import APP_NAME, APP_TAGLINE
from src.scoring.score_config import validate_weights
from src.ui import (
    candidates,
    discovery,
    federated,
    memo,
    ranking,
    research,
    shortlist,
    state,
    theme,
)

st.set_page_config(
    page_title=APP_NAME,
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = {
    "Discovery": discovery.render,
    "Candidates": candidates.render,
    "Company research": research.render,
    "Ranking": ranking.render,
    "Investment memo": memo.render,
    "Final shortlist": shortlist.render,
    "Federated calibration": federated.render,
}


def main() -> None:
    theme.inject()

    # Fail loudly and early if the scoring framework no longer sums to 100.
    try:
        validate_weights()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    state.init_state()
    state.render_sidebar()

    theme.masthead(APP_NAME, APP_TAGLINE)

    tabs = st.tabs(list(PAGES.keys()))
    for tab, render in zip(tabs, PAGES.values()):
        with tab:
            try:
                render()
            except Exception as exc:  # noqa: BLE001 — one broken page must not kill the app
                st.error(f"Something went wrong rendering this page: {exc}")
                with st.expander("Technical details"):
                    import traceback

                    st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
