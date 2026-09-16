"""Federated calibration of the scoring framework's weights.

The framework's 8 weights (src/scoring/score_config.py) are one person's
judgement call. This package lets many funds jointly learn a *market* view of
which criteria actually predict a shortlist decision — via Flower — without
any fund's deal flow ever leaving its own machine.

The model never predicts startup success. It predicts one thing only:
``P(a partner would shortlist this company | its 8 criterion ratings)``.
That keeps it inside the project's existing disclaimer (APP_DISCLAIMER in
src/config.py): scores stay explainable, the investor still decides.
"""
