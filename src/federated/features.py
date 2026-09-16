"""Turn a scored ``Startup`` into a fixed-order feature vector for the FL model.

Each of the 8 scoring criteria (src/scoring/score_config.py) becomes 2
features: ``rating / 5`` and an evidence-present flag. The flag matters
because ``raw_rating is None`` ("no evidence") and ``raw_rating == 0``
("assessed as zero") mean different things in this codebase — see
``CriterionScore`` in src/models/scoring.py — and collapsing them would
silently throw that distinction away.

16 features total, always in ``CRITERIA`` order, so parameters trained on one
fund's data line up with every other fund's when Flower averages them.
"""

from __future__ import annotations

import numpy as np

from ..models.startup import Startup
from ..scoring.score_config import CRITERIA

FEATURE_NAMES: list[str] = [
    name for c in CRITERIA for name in (f"{c.key}__rating", f"{c.key}__has_evidence")
]
NUM_FEATURES = len(FEATURE_NAMES)  # 16


def to_features(startup: Startup) -> np.ndarray | None:
    """8 criteria -> 16 features, or None if the company hasn't been scored yet."""
    breakdown = startup.score_breakdown
    if breakdown is None or not breakdown.criteria:
        return None

    row: list[float] = []
    for criterion in CRITERIA:
        scored = breakdown.get(criterion.key)
        if scored is None or scored.raw_rating is None:
            row.extend((0.0, 0.0))
        else:
            row.extend((scored.raw_rating / 5.0, 1.0))
    return np.array(row, dtype=np.float32)


def build_dataset(startups: list[Startup]) -> tuple[np.ndarray, np.ndarray]:
    """Stack every scored startup into (X, y). Unscored companies are skipped.

    y = 1 iff a human partner actually added the company to the shortlist —
    the only label in this codebase that reflects a real investment judgement
    rather than the deterministic score itself.
    """
    features, labels = [], []
    for startup in startups:
        vector = to_features(startup)
        if vector is not None:
            features.append(vector)
            labels.append(int(startup.shortlisted))

    if not features:
        return np.empty((0, NUM_FEATURES), dtype=np.float32), np.empty((0,), dtype=np.int64)
    return np.vstack(features), np.array(labels, dtype=np.int64)
