"""Proves the real SecAgg+ protocol actually completes, not just imports cleanly.

Skipped by default: it spins up a real Ray cluster and drives the genuine
Shamir-secret-sharing / pairwise-masking handshake across simulated fund
clients — slow (tens of seconds) compared to the rest of the suite, and on
Windows Ray's shutdown path is known to print a harmless access-violation
traceback from the raylet *after* the simulation has already returned its
result (see client_app.py / server_app.py docstrings). That's noise in the
process teardown, not a protocol failure — this test only checks what
happened *during* the run, via the log lines Flower's own SecAgg+ workflow
emits ("Secure aggregation commencing/completed", failure counts).

Run explicitly with:

    RUN_SECAGG_INTEGRATION_TEST=1 pytest tests/test_secagg_integration.py -s
"""

from __future__ import annotations

import logging
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_SECAGG_INTEGRATION_TEST") != "1",
    reason="Needs Ray and takes ~15-30s; opt in with RUN_SECAGG_INTEGRATION_TEST=1.",
)

def test_secaggplus_workflow_runs_every_round_with_no_failures(caplog):
    """Runs server_app.py's real default (num-funds=8, 20 rounds) end to end.

    ``num_supernodes`` must equal the server's configured ``num-funds`` — the
    SecAgg+ workflow sizes its Shamir shares off that count, and mismatching
    them is exactly what produces "Insufficient available nodes" errors
    (discovered the hard way while wiring this up).
    """
    from flwr.simulation import run_simulation

    from src.federated.client_app import app as client_app
    from src.federated.server_app import app as server_app

    with caplog.at_level(logging.INFO):
        run_simulation(
            server_app=server_app,
            client_app=client_app,
            num_supernodes=8,
            backend_config={"client_resources": {"num_cpus": 1, "num_gpus": 0}},
        )

    messages = [record.getMessage() for record in caplog.records]
    commenced = messages.count("Secure aggregation commencing.")
    completed = messages.count("Secure aggregation completed.")

    assert commenced >= 1, "SecAgg+ workflow never ran — check the client/server mod wiring."
    assert completed == commenced, "Some round(s) commenced secure aggregation but never completed."
    assert not any("Insufficient available nodes" in m for m in messages)
    assert all(
        "0 failures" in m for m in messages if m.startswith("aggregate_fit: received")
    )
