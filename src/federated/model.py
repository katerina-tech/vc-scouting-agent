"""A logistic regression wrapped for Flower's NumPyClient parameter protocol.

Deliberately not a neural net: 17 parameters (16 weights + bias) map one-to-one
onto the 8 hand-set criteria in score_config.py, so the federated weights can
be shown *next to* the house weights instead of replacing them with a black
box. It also converges in milliseconds on CPU, which matters for a live demo.
"""

from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

from .features import NUM_FEATURES

# Both classes must be present at least once before sklearn can be scored /
# used to predict_proba with two columns. Fabricated as neutral padding so a
# fund whose shortlist is all-yes or all-no can still participate in a round.
_CLASSES = np.array([0, 1])


def new_model() -> LogisticRegression:
    return LogisticRegression(
        warm_start=True,
        max_iter=1,          # one local epoch per FL round; Flower drives the rounds
        C=1.0,
    )


def get_params(model: LogisticRegression) -> list[np.ndarray]:
    if not hasattr(model, "coef_"):
        return [np.zeros((1, NUM_FEATURES), dtype=np.float64), np.zeros((1,), dtype=np.float64)]
    return [model.coef_, model.intercept_]


def set_params(model: LogisticRegression, params: list[np.ndarray]) -> LogisticRegression:
    model.coef_ = params[0]
    model.intercept_ = params[1]
    model.classes_ = _CLASSES
    return model


def ensure_initialised(model: LogisticRegression) -> LogisticRegression:
    """Give sklearn the attributes it expects before the first real .fit()."""
    if not hasattr(model, "coef_"):
        model.classes_ = _CLASSES
        model.coef_ = np.zeros((1, NUM_FEATURES), dtype=np.float64)
        model.intercept_ = np.zeros((1,), dtype=np.float64)
    return model
