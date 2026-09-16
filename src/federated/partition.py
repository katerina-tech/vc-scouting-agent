"""Synthetic fund partitions with a known ground-truth preference vector.

The real dataset (data/*.csv) has ~25 companies total — nowhere near enough to
learn anything, and that has to be solved *before* a demo, not discovered on
stage. This module generates N synthetic "funds", each with its own latent
weighting over the 8 criteria, so a demo can show FedAvg recovering a known
answer instead of just producing numbers nobody can check.

Each fund's ratings and evidence-presence are drawn independently (non-IID
sparsity per fund, mirroring how real deal flow varies in how well it's
researched), then labelled by that fund's *own* latent weights plus noise —
i.e. every fund's local model would overfit to its own taste, which is
exactly the situation FedAvg is meant to average out.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..scoring.score_config import CRITERIA
from .features import NUM_FEATURES

NUM_CRITERIA = len(CRITERIA)


@dataclass(frozen=True)
class FundPartition:
    fund_id: str
    X: np.ndarray            # (n_companies, 16)
    y: np.ndarray            # (n_companies,)
    true_criterion_weights: np.ndarray  # (8,) — this fund's latent taste, for grading the demo


def _make_market_weights(rng: np.random.Generator) -> np.ndarray:
    """One shared 'ground truth' the whole synthetic market is built around.

    Modelled loosely on the house weights (thesis_fit and problem_magnitude
    dominate) but not copied verbatim, so recovering it is a real test of the
    federated round rather than an artifact of matching config values.
    """
    base = np.array([0.22, 0.20, 0.16, 0.14, 0.10, 0.08, 0.05, 0.05])
    return base / base.sum()


def make_fund(
    fund_id: str,
    rng: np.random.Generator,
    market_weights: np.ndarray,
    n_companies: int = 40,
    personalization: float = 0.15,
    evidence_rate: float = 0.75,
    label_noise: float = 0.08,
) -> FundPartition:
    """One synthetic fund: its own evidence sparsity, its own taste, a shared market signal."""
    # This fund's taste = shared market prior + a personal tilt (non-IID).
    tilt = rng.normal(scale=personalization, size=NUM_CRITERIA)
    true_weights = np.clip(market_weights + tilt, 0.01, None)
    true_weights = true_weights / true_weights.sum()

    ratings = rng.integers(0, 6, size=(n_companies, NUM_CRITERIA)).astype(np.float64)
    has_evidence = rng.random((n_companies, NUM_CRITERIA)) < evidence_rate

    X = np.zeros((n_companies, NUM_FEATURES), dtype=np.float32)
    X[:, 0::2] = np.where(has_evidence, ratings / 5.0, 0.0)
    X[:, 1::2] = has_evidence.astype(np.float32)

    score = (np.where(has_evidence, ratings / 5.0, 0.0) @ true_weights)
    score += rng.normal(scale=label_noise, size=n_companies)
    threshold = np.quantile(score, 0.7)  # top 30% of a fund's own pipeline gets shortlisted
    y = (score >= threshold).astype(np.int64)

    return FundPartition(fund_id=fund_id, X=X, y=y, true_criterion_weights=true_weights)


def make_synthetic_market(
    num_funds: int = 8,
    n_companies_per_fund: int = 40,
    seed: int = 42,
) -> tuple[list[FundPartition], np.ndarray]:
    """N funds drawn around one shared market signal. Returns (funds, market_weights)."""
    rng = np.random.default_rng(seed)
    market_weights = _make_market_weights(rng)
    funds = [
        make_fund(f"fund_{i:02d}", rng, market_weights, n_companies=n_companies_per_fund)
        for i in range(num_funds)
    ]
    return funds, market_weights
