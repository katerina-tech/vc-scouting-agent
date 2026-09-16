"""Page — Federated calibration.

The house weights in src/scoring/score_config.py (20/20/15/15/10/10/5/5) are
one person's judgement call. This page runs Flower-style federated averaging
(FedAvg) across several funds' *private* deal flow to learn a market view of
which criteria actually predict a shortlist decision — without any fund's
companies ever being pooled or shared.

Two things stay true throughout, matching the rest of this application:
  * the deterministic score never changes silently — federated weights are a
    side-by-side comparison, applied only if the investor asks to see it;
  * nothing here predicts startup success. It predicts an investor's own past
    shortlist behaviour, which is a much smaller and more honest claim.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from ..federated.dp import DPConfig, estimate_epsilon
from ..federated.orchestrator import FederatedRun, run_fedavg
from ..federated.partition import make_synthetic_market
from ..federated.reweigh import market_weights_out_of_100, reweigh
from ..scoring.score_config import CRITERIA
from . import state, theme
from .components import disclaimer, empty_state

_STATE_KEY = "federated_run"
_MARKET_KEY = "federated_market_weights"
_META_KEY = "federated_run_meta"

#: Fictional but concrete names -- seeing named, separate funds side by side
#: makes "why can't they just pool their data" obvious without a word of
#: explanation, the way an anonymous "Funds: 8" slider never could.
_FUND_NAMES = [
    "Nordkap Ventures", "Rhône Capital", "Baltic Seed Partners", "Alpine Frontier",
    "Adria Growth", "Danube Angels", "Iberia Ventures", "Helvetia Partners",
    "Elbe Capital", "Tyrrhenian Fund", "Vistula Ventures", "Aegean Seed",
    "Carpathian Capital", "Flanders Growth", "Douro Ventures", "Meridian North",
    "Fjord Capital", "Lagoon Partners", "Steppe Ventures", "Delta Nordic",
]


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denom) if denom else 0.0


def _run_simulation(
    num_funds: int,
    companies_per_fund: int,
    num_rounds: int,
    seed: int,
    dp: DPConfig | None,
) -> None:
    funds, market_weights = make_synthetic_market(
        num_funds=num_funds, n_companies_per_fund=companies_per_fund, seed=seed
    )
    result = run_fedavg(funds, num_rounds=num_rounds, dp=dp, rng=np.random.default_rng(seed))
    st.session_state[_STATE_KEY] = result
    st.session_state[_MARKET_KEY] = market_weights
    st.session_state[_META_KEY] = {"num_funds": num_funds, "num_rounds": num_rounds, "dp": dp}


def _fund_hub(num_funds: int, companies_per_fund: int) -> None:
    st.markdown("###### The funds in this round")
    names = [_FUND_NAMES[i % len(_FUND_NAMES)] for i in range(num_funds)]
    per_row = 4
    for row_start in range(0, num_funds, per_row):
        row_names = names[row_start:row_start + per_row]
        cols = st.columns(per_row)
        for col, name in zip(cols, row_names):
            col.markdown(
                '<div class="vc-source-card" style="text-align:center; padding:0.7rem 0.5rem;'
                'border-top-color:var(--accent)">'
                f'<div style="font-weight:600">{name}</div>'
                f'<div class="vc-note">{companies_per_fund} companies · private pipeline</div>'
                "</div>",
                unsafe_allow_html=True,
            )
    st.caption(
        f"{num_funds} separate funds, {num_funds} separate databases. None of them can see "
        "another's pipeline before, during, or after this round."
    )


def _controls() -> tuple[int, int, int, int, DPConfig | None]:
    st.markdown("#### Run a federated round")
    st.caption(
        "Simulates several independent funds, each with its own private pipeline and its "
        "own taste, jointly training one shared model of 'what gets shortlisted' — via "
        "Flower's client/server protocol, with no fund's companies ever pooled."
    )
    cols = st.columns(4)
    num_funds = cols[0].slider("Funds", 2, 20, 8)
    companies_per_fund = cols[1].slider("Companies / fund", 10, 200, 40, step=10)
    _fund_hub(num_funds, companies_per_fund)
    num_rounds = cols[2].slider("Rounds", 5, 50, 20)
    seed = cols[3].number_input("Seed", value=42, step=1)

    dp: DPConfig | None = None
    with st.expander("Differential privacy (optional)"):
        st.caption(
            "Clips each fund's update to a fixed size, then adds calibrated noise to the "
            "aggregate before the next round — so the shared model can't be reverse-"
            "engineered to reveal any single fund's data. Same mechanism as Flower's "
            "``DifferentialPrivacyServerSideFixedClipping`` strategy (McMahan et al., "
            "arXiv:1710.06963)."
        )
        dp_enabled = st.checkbox("Apply differential privacy to this run", value=False)
        if dp_enabled:
            dp_cols = st.columns(2)
            clipping_norm = dp_cols[0].slider(
                "Clipping norm", 0.05, 5.0, 0.5, step=0.05,
                help="Maximum L2 size of any single fund's update, per round.",
            )
            noise_multiplier = dp_cols[1].slider(
                "Noise multiplier", 0.0, 4.0, 1.0, step=0.1,
                help="Higher = more noise = stronger privacy, weaker signal.",
            )
            dp = DPConfig(clipping_norm=clipping_norm, noise_multiplier=noise_multiplier)
            if noise_multiplier > 0:
                epsilon = estimate_epsilon(dp, num_clients=num_funds, num_rounds=num_rounds)
                st.caption(
                    f"Estimated privacy budget after {num_rounds} rounds: **ε ≈ {epsilon:.2f}** "
                    "(δ=1e-5). This is a basic-composition bound, not a tight accountant — "
                    "treat it as an order-of-magnitude signal, not a certified guarantee."
                )

    if st.button("Run federated simulation", type="primary", width="stretch"):
        with st.spinner("Running FedAvg across funds..."):
            _run_simulation(num_funds, companies_per_fund, num_rounds, int(seed), dp)
        st.rerun()

    return num_funds, companies_per_fund, num_rounds, int(seed), dp


def _convergence_chart(result: FederatedRun) -> None:
    import plotly.graph_objects as go

    rounds = [r.round_number for r in result.rounds]
    loss = [r.aggregated_loss for r in result.rounds]
    accuracy = [r.aggregated_accuracy for r in result.rounds]

    figure = go.Figure()
    figure.add_scatter(x=rounds, y=loss, name="Loss", mode="lines", line=dict(color=theme.NAVY))
    figure.add_scatter(
        x=rounds, y=accuracy, name="Accuracy", mode="lines",
        line=dict(color=theme.ACCENT), yaxis="y2",
    )
    figure.update_layout(
        **theme.plotly_layout(
            height=300,
            xaxis_title="Round",
            yaxis=dict(title="Loss", gridcolor=theme.RULE),
            yaxis2=dict(title="Accuracy", overlaying="y", side="right", range=[0, 1], gridcolor="rgba(0,0,0,0)"),
        )
    )
    st.plotly_chart(figure, width="stretch", key="federated_convergence")


def _weights_comparison_chart(result: FederatedRun, market_weights: np.ndarray | None) -> None:
    import plotly.graph_objects as go

    labels = [c.label for c in CRITERIA]
    house = [c.weight for c in CRITERIA]
    federated = [w * 100 for w in result.criterion_weights]

    figure = go.Figure()
    figure.add_bar(x=labels, y=house, name="Your weights (guess)", marker_color=theme.NAVY)
    figure.add_bar(x=labels, y=federated, name="Learned from all funds", marker_color=theme.ACCENT)
    if market_weights is not None:
        planted = [w * 100 for w in market_weights]
        figure.add_bar(x=labels, y=planted, name="Hidden answer (test only)",
                       marker_color=theme.ACCENT_SOFT)
    figure.update_layout(barmode="group", **theme.plotly_layout(height=340, yaxis_title="Weight (of 100)"))
    st.plotly_chart(figure, width="stretch", key="federated_weights_chart")

    if market_weights is not None:
        similarity = _cosine(result.criterion_weights, market_weights)
        st.caption(
            f"For this test we hid the 'right' answer and only let each fund see its own "
            f"noisy, incomplete ratings. What came back matches the hidden answer by "
            f"**{similarity:.0%}** ({similarity:.3f} cosine similarity) — without any fund "
            f"comparing notes with another."
        )


def _whatif_ranking(result: FederatedRun) -> None:
    st.markdown("#### What changes in this dataset")
    st.caption(
        "Applying the federated weights to the companies already scored here — a "
        "side-by-side comparison only. It does not overwrite anything in storage."
    )
    scored = [s for s in state.startups() if s.score_breakdown is not None]
    if not scored:
        empty_state(
            "No scored companies in this dataset yet.",
            "Score a few companies on the Candidates or Ranking page, then come back here.",
        )
        return

    market_weights = market_weights_out_of_100(list(result.criterion_weights))
    rows = []
    for startup in scored:
        house_total = startup.score_breakdown.score_total
        federated_breakdown = reweigh(startup.score_breakdown, market_weights)
        rows.append({
            "Company": startup.display_name,
            "House score": house_total,
            "Federated score": federated_breakdown.score_total,
            "Delta": round(federated_breakdown.score_total - house_total, 1),
        })

    frame = pd.DataFrame(rows).sort_values("Federated score", ascending=False).reset_index(drop=True)
    frame.insert(0, "Federated rank", frame.index + 1)
    frame["House rank"] = frame["House score"].rank(ascending=False, method="min").astype(int)
    frame = frame[["Federated rank", "House rank", "Company", "House score", "Federated score", "Delta"]]
    st.dataframe(frame, hide_index=True, width="stretch")


def render() -> None:
    theme.page_header(
        "Why this exists",
        "Federated calibration",
        "The 20/20/15/15/10/10/5/5 weights on the Ranking page are one person's judgement "
        "call. Every other fund is guessing too — and no fund will ever show you which "
        "deals it actually took, because that's their edge.",
    )

    theme.callout(
        "So instead of asking funds to share deals, we let them share an answer. Each fund "
        "scores its own private pipeline and sends back one encrypted number — never a "
        "company name, never a rating anyone could trace to a real deal. Add those numbers "
        "up across funds and what comes out is a weighting the whole market actually agrees "
        "with — without a single deal ever leaving the fund that made it."
    )
    st.caption(
        "This is the same scoring agent you saw on the Company research page — the one that "
        "can be overruled by its own team's risk and evidence agents before a recommendation "
        "ever ships. Here, that one agent also compares notes with every other fund's, safely, "
        "through Flower."
    )

    _controls()
    theme.rule()

    result: FederatedRun | None = st.session_state.get(_STATE_KEY)
    if result is None:
        empty_state(
            "No federated run yet.",
            "Run a simulation above to see the convergence and the learned weights.",
        )
        disclaimer()
        return

    meta = st.session_state.get(_META_KEY) or {}
    dp_used: DPConfig | None = meta.get("dp")
    if dp_used is not None:
        epsilon = estimate_epsilon(dp_used, meta.get("num_funds", 8), meta.get("num_rounds", 20))
        theme.callout(
            f"This run applied differential privacy: clipping norm {dp_used.clipping_norm:g}, "
            f"noise multiplier {dp_used.noise_multiplier:g}, noise σ ≈ {result.rounds[-1].noise_std:.4f} "
            f"per round → estimated ε ≈ {epsilon:.2f} (loose bound, see caption above)."
        )

    left, right = st.columns(2)
    with left:
        st.markdown("#### Convergence")
        _convergence_chart(result)
    with right:
        st.markdown("#### Learned weights vs. house weights")
        _weights_comparison_chart(result, st.session_state.get(_MARKET_KEY))

    theme.rule()
    _whatif_ranking(result)

    disclaimer()
