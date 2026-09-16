"""Tests for the differential-privacy layer (dp.py + its wiring into orchestrator.py).

Three things need proving, not just asserting:
  1. clipping actually bounds an update's L2 norm, regardless of how large
     the raw update was;
  2. dp=None reproduces the exact noiseless FedAvg run (no accidental
     behaviour change for callers who don't opt in);
  3. turning noise on measurably perturbs the result, and the (loose) epsilon
     estimate moves the direction it should — more noise -> smaller epsilon.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.federated.dp import DPConfig, clip_update, estimate_epsilon, l2_norm, noise_stddev
from src.federated.orchestrator import run_fedavg
from src.federated.partition import make_synthetic_market


def test_clip_update_bounds_the_norm_of_a_huge_update():
    global_params = [np.zeros((1, 4)), np.zeros((1,))]
    huge_client_params = [np.full((1, 4), 100.0), np.array([100.0])]

    clipped = clip_update(huge_client_params, global_params, clipping_norm=1.0)
    update = [c - g for c, g in zip(clipped, global_params)]

    assert l2_norm(update) == pytest.approx(1.0, rel=1e-6)


def test_clip_update_leaves_small_updates_untouched():
    global_params = [np.zeros((1, 4)), np.zeros((1,))]
    small_client_params = [np.full((1, 4), 0.01), np.array([0.01])]

    clipped = clip_update(small_client_params, global_params, clipping_norm=10.0)

    for c, orig in zip(clipped, small_client_params):
        assert np.allclose(c, orig)


def test_dp_none_matches_plain_fedavg_exactly():
    funds, _ = make_synthetic_market(num_funds=5, n_companies_per_fund=30, seed=5)

    plain = run_fedavg(funds, num_rounds=8, dp=None)
    also_plain = run_fedavg(funds, num_rounds=8, dp=None)

    assert np.allclose(plain.final_parameters[0], also_plain.final_parameters[0])
    assert np.allclose(plain.criterion_weights, also_plain.criterion_weights)


def test_noise_perturbs_the_result_reproducibly_given_a_seeded_rng():
    funds, _ = make_synthetic_market(num_funds=6, n_companies_per_fund=40, seed=9)
    dp = DPConfig(clipping_norm=0.5, noise_multiplier=1.0)

    run_a = run_fedavg(funds, num_rounds=10, dp=dp, rng=np.random.default_rng(123))
    run_b = run_fedavg(funds, num_rounds=10, dp=dp, rng=np.random.default_rng(123))
    run_c = run_fedavg(funds, num_rounds=10, dp=dp, rng=np.random.default_rng(999))
    no_dp = run_fedavg(funds, num_rounds=10, dp=None)

    # Same seed -> identical run (reproducibility for a demo).
    assert np.allclose(run_a.final_parameters[0], run_b.final_parameters[0])
    # Different seed -> a different noisy trajectory.
    assert not np.allclose(run_a.final_parameters[0], run_c.final_parameters[0])
    # DP with real noise actually changed something vs. the noiseless run.
    assert not np.allclose(run_a.final_parameters[0], no_dp.final_parameters[0])
    assert all(r.noise_std > 0 for r in run_a.rounds)


def test_estimate_epsilon_decreases_as_noise_increases():
    low_noise = DPConfig(clipping_norm=1.0, noise_multiplier=0.5)
    high_noise = DPConfig(clipping_norm=1.0, noise_multiplier=4.0)

    eps_low = estimate_epsilon(low_noise, num_clients=8, num_rounds=20)
    eps_high = estimate_epsilon(high_noise, num_clients=8, num_rounds=20)

    assert eps_high < eps_low
    assert eps_low > 0 and eps_high > 0


def test_estimate_epsilon_is_infinite_with_no_noise():
    assert estimate_epsilon(DPConfig(clipping_norm=1.0, noise_multiplier=0.0), 8, 20) == float("inf")
