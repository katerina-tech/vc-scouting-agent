"""Proves the federated pipeline actually does something, before wiring up UI.

The central risk in this feature isn't Flower plumbing, it's whether FedAvg
over per-fund logistic regressions converges toward a sane answer at all. This
test builds synthetic funds around a *known* latent weighting (partition.py),
runs the exact FedAvg loop the demo uses (orchestrator.py, which drives the
same FundClient as the real ClientApp), and checks the recovered weights
resemble the planted market signal rather than noise.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.federated.features import NUM_FEATURES, to_features
from src.federated.model import ensure_initialised, get_params, new_model
from src.federated.orchestrator import run_fedavg
from src.federated.partition import make_synthetic_market
from src.models.enums import Dataset
from src.models.scoring import CriterionScore, ScoreBreakdown
from src.models.startup import Startup
from src.scoring.score_config import CRITERIA


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def test_untrained_model_has_zeroed_parameters():
    model = ensure_initialised(new_model())
    coef, intercept = get_params(model)
    assert coef.shape == (1, NUM_FEATURES)
    assert intercept.shape == (1,)
    assert np.all(coef == 0.0)


def test_features_distinguish_missing_evidence_from_zero_rating():
    """raw_rating=None and raw_rating=0 must not collapse to the same vector."""
    def make(rating):
        breakdown = ScoreBreakdown(
            criteria=[
                CriterionScore(criterion=c.key, label=c.label, weight=c.weight, raw_rating=rating if i == 0 else None)
                for i, c in enumerate(CRITERIA)
            ]
        )
        return Startup(company_name="Acme", dataset=Dataset.DEMO, score_breakdown=breakdown)

    zero_rated = to_features(make(0))
    no_evidence = to_features(make(None))

    assert zero_rated[1] == 1.0   # has_evidence flag set
    assert no_evidence[1] == 0.0  # has_evidence flag unset
    assert zero_rated[0] == 0.0 and no_evidence[0] == 0.0  # rating value identical either way
    assert not np.array_equal(zero_rated, no_evidence)


def test_unscored_startup_yields_no_features():
    startup = Startup(company_name="Unscored Co", dataset=Dataset.DEMO)
    assert to_features(startup) is None


@pytest.mark.parametrize("num_funds", [3, 8])
def test_fedavg_recovers_planted_market_weights(num_funds):
    funds, market_weights = make_synthetic_market(
        num_funds=num_funds, n_companies_per_fund=60, seed=7
    )

    result = run_fedavg(funds, num_rounds=25)

    similarity = _cosine(result.criterion_weights, market_weights)
    assert similarity > 0.85, (
        f"FedAvg diverged from the planted market signal (cosine={similarity:.3f}); "
        f"got {result.criterion_weights}, expected close to {market_weights}"
    )


def test_fedavg_loss_improves_over_rounds():
    funds, _ = make_synthetic_market(num_funds=6, n_companies_per_fund=50, seed=11)
    result = run_fedavg(funds, num_rounds=15)

    first_loss = result.rounds[0].aggregated_loss
    last_loss = result.rounds[-1].aggregated_loss
    assert last_loss < first_loss


def test_criterion_weights_sum_to_one_and_are_nonnegative():
    funds, _ = make_synthetic_market(num_funds=5, n_companies_per_fund=30, seed=3)
    result = run_fedavg(funds, num_rounds=10)

    assert np.all(result.criterion_weights >= 0.0)
    assert result.criterion_weights.sum() == pytest.approx(1.0, abs=1e-6)
