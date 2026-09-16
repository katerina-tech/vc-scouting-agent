"""A dependency-free FedAvg driver for live demos and tests.

Flower's own simulation engine (``flwr.simulation.run_simulation``) requires
Ray as its execution backend. Ray is heavy, spins up a local process cluster,
and its Windows support is a real risk to take on a few hours before a
hackathon demo has to run live on stage. This module runs exactly the same
``FundClient`` (the ``flwr.client.NumPyClient`` from client_app.py) through a
plain-Python FedAvg loop instead — same client contract, same aggregation
math, no subprocess, no extra dependency.

For an actual multi-fund deployment (real SuperNodes on real fund
infrastructure, not a single-process demo), use ``flwr run`` against
client_app.py / server_app.py instead — that path is unchanged and Flower's
Ray simulation engine remains a legitimate way to test it before deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .client_app import FundClient
from .dp import DPConfig, add_noise, clip_update, noise_stddev
from .features import NUM_FEATURES
from .model import ensure_initialised, get_params, new_model
from .partition import FundPartition


@dataclass
class RoundMetrics:
    round_number: int
    aggregated_loss: float
    aggregated_accuracy: float
    per_fund_accuracy: dict[str, float] = field(default_factory=dict)
    noise_std: float = 0.0


@dataclass
class FederatedRun:
    rounds: list[RoundMetrics]
    final_parameters: list[np.ndarray]        # [coef_ (1,16), intercept_ (1,)]
    criterion_weights: np.ndarray             # (8,) — final_parameters folded down to one per criterion


def _fold_to_criterion_weights(coef: np.ndarray) -> np.ndarray:
    """16 signed feature weights -> 8 non-negative, sum-to-one criterion weights.

    Only the ``__rating`` half of each pair drives the score; the
    ``__has_evidence`` half exists so the model can separate "no evidence"
    from "rated zero" (see features.py) but isn't itself a criterion weight.
    Negative learned weights are clipped to 0 before renormalising, matching
    the house framework's assumption that every criterion helps, never hurts.
    """
    rating_weights = np.clip(coef.reshape(-1)[0::2], 0.0, None)
    total = rating_weights.sum()
    if total <= 0:
        return np.full(NUM_FEATURES // 2, 1.0 / (NUM_FEATURES // 2))
    return rating_weights / total


def run_fedavg(
    partitions: list[FundPartition],
    num_rounds: int = 20,
    dp: DPConfig | None = None,
    rng: np.random.Generator | None = None,
) -> FederatedRun:
    """Federated averaging across pre-loaded fund partitions (synthetic or real).

    Each round: broadcast global params -> every fund fits one local epoch on
    its own private (X, y) -> server averages the returned params, weighted by
    how many companies that fund contributed -> repeat. No fund's X or y is
    ever read outside its own FundClient instance.

    When ``dp`` is given, each fund's returned update is first clipped to a
    fixed L2 norm and the aggregate is perturbed with calibrated Gaussian
    noise before the next round starts — see dp.py. Passing ``dp=None``
    (the default) reproduces the original, noiseless FedAvg exactly.
    """
    clients = [FundClient(p.fund_id, p.X, p.y) for p in partitions]
    global_params = get_params(ensure_initialised(new_model()))

    history: list[RoundMetrics] = []
    for round_number in range(1, num_rounds + 1):
        params_before_round = global_params
        fit_results = [client.fit(global_params, {}) for client in clients]

        if dp is not None:
            fit_results = [
                (clip_update(params, params_before_round, dp.clipping_norm), n, m)
                for params, n, m in fit_results
            ]

        total_examples = sum(n for _, n, _ in fit_results) or 1
        global_params = [
            sum(params[i] * n for params, n, _ in fit_results) / total_examples
            for i in range(len(global_params))
        ]

        round_noise_std = 0.0
        if dp is not None:
            round_noise_std = noise_stddev(dp.noise_multiplier, dp.clipping_norm, len(clients))
            if round_noise_std > 0:
                global_params = add_noise(global_params, round_noise_std, rng)

        eval_results = [client.evaluate(global_params, {}) for client in clients]
        losses = np.array([loss for loss, _, _ in eval_results])
        weights = np.array([n for _, n, _ in eval_results], dtype=np.float64)
        weights /= weights.sum() or 1
        per_fund_accuracy = {m["fund_id"]: m["accuracy"] for _, _, m in eval_results}

        history.append(
            RoundMetrics(
                round_number=round_number,
                aggregated_loss=float(np.average(losses, weights=weights)),
                aggregated_accuracy=float(sum(w * m["accuracy"] for w, (_, _, m) in zip(weights, eval_results))),
                per_fund_accuracy=per_fund_accuracy,
                noise_std=round_noise_std,
            )
        )

    criterion_weights = _fold_to_criterion_weights(global_params[0])
    return FederatedRun(rounds=history, final_parameters=global_params, criterion_weights=criterion_weights)
