"""Apply an alternative weight vector to an existing score breakdown.

This is a "what if" view, not a write path: it returns a fresh
``ScoreBreakdown`` with the same ratings, evidence and reasoning but
different weights, so a federated (or any custom) weighting can be compared
against the house framework's 20/20/15/15/10/10/5/5 without touching the
stored, audited score. Nothing here is persisted — see src/ui/federated.py
for where a user would deliberately choose to apply it.
"""

from __future__ import annotations

from ..models.scoring import ScoreBreakdown
from ..scoring.score_config import CRITERIA


def reweigh(breakdown: ScoreBreakdown, criterion_weights: dict[str, float]) -> ScoreBreakdown:
    """Copy ``breakdown`` with each criterion's weight swapped for ``criterion_weights``.

    ``criterion_weights`` maps criterion key -> weight out of 100 (i.e. it
    should sum to ~100, matching the house framework's scale). A criterion
    missing from the map keeps its original weight.
    """
    new_breakdown = breakdown.model_copy(deep=True)
    for criterion_score in new_breakdown.criteria:
        if criterion_score.criterion in criterion_weights:
            criterion_score.weight = criterion_weights[criterion_score.criterion]
    return new_breakdown


def market_weights_out_of_100(criterion_weights: "list[float] | dict") -> dict[str, float]:
    """The federated model's 8 fractional weights (sum to 1) -> a criterion-key map out of 100."""
    if isinstance(criterion_weights, dict):
        return {key: value * 100 for key, value in criterion_weights.items()}
    return {c.key: float(w) * 100 for c, w in zip(CRITERIA, criterion_weights)}
