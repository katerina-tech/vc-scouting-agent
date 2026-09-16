"""Central differential privacy for FedAvg: fixed clipping + Gaussian noise.

Same algorithm Flower's own strategy wrappers implement
(``DifferentialPrivacyServerSideFixedClipping`` /
``DPFedAvgFixed``, see flwr.supercore.differential_privacy) — reimplemented
here in ~30 lines rather than imported, because that module lives under
``flwr.supercore`` (not part of Flower's public API surface) and this
demo needs the math to keep working across Flower point releases:

    1. Each fund's update (fitted params - global params before the round)
       is clipped to a fixed L2 norm, so no single fund's contribution can
       dominate or be reverse-engineered from the aggregate's magnitude.
    2. The aggregator adds calibrated Gaussian noise to the averaged update.

Reference: McMahan et al., "Learning Differentially Private Recurrent
Language Models", https://arxiv.org/abs/1710.06963
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DPConfig:
    clipping_norm: float
    noise_multiplier: float


def l2_norm(arrays: list[np.ndarray]) -> float:
    return float(np.sqrt(sum(float(np.sum(a.astype(np.float64) ** 2)) for a in arrays)))


def clip_update(
    client_params: list[np.ndarray],
    global_params: list[np.ndarray],
    clipping_norm: float,
) -> list[np.ndarray]:
    """Return ``global_params + clip(client_params - global_params, clipping_norm)``.

    FlatClip: the whole update is scaled down by one factor (never per-layer),
    so relative direction is preserved — only magnitude is bounded.
    """
    update = [c - g for c, g in zip(client_params, global_params)]
    norm = l2_norm(update)
    scale = min(1.0, clipping_norm / norm) if norm > 0 else 1.0
    return [g + u * scale for g, u in zip(global_params, update)]


def noise_stddev(noise_multiplier: float, clipping_norm: float, num_clients: int) -> float:
    """Gaussian noise std-dev calibrated to the clipping norm and cohort size.

    Averaging over ``num_clients`` shrinks each client's worst-case
    contribution to the sum by that factor, so the noise needed to mask one
    clipped update shrinks with it too.
    """
    return (noise_multiplier * clipping_norm) / max(num_clients, 1)


def add_noise(
    arrays: list[np.ndarray], std_dev: float, rng: np.random.Generator | None = None
) -> list[np.ndarray]:
    generator = rng or np.random.default_rng()
    return [a + generator.normal(0.0, std_dev, size=a.shape).astype(a.dtype) for a in arrays]


def estimate_epsilon(
    dp: DPConfig, num_clients: int, num_rounds: int, delta: float = 1e-5
) -> float:
    """A loose, basic-composition privacy bound — NOT a tight accountant.

    Per-round epsilon from the analytic Gaussian mechanism
    (sensitivity = clipping_norm / num_clients, sigma = noise_stddev),
    summed linearly across rounds. Real deployments should replace this with
    a proper moments/RDP accountant (e.g. Google's ``dp_accounting`` or
    Opacus) before quoting an epsilon to anyone outside a demo — basic
    composition overstates the true privacy cost substantially for many
    rounds.
    """
    if dp.noise_multiplier <= 0:
        return float("inf")
    sigma = noise_stddev(dp.noise_multiplier, dp.clipping_norm, num_clients)
    sensitivity = dp.clipping_norm / max(num_clients, 1)
    per_round = (sensitivity * np.sqrt(2 * np.log(1.25 / delta))) / sigma
    return float(per_round * num_rounds)
