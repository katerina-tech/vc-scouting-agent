"""The Flower ServerApp: FedAvg over fund-local logistic regressions, under SecAgg+.

FedAvg on a linear model's coefficients is a coherent thing to average (unlike
deep nets, there's no permutation-symmetry problem) — the aggregate is just a
weighted mean of each fund's fitted decision boundary. That's what makes
logistic regression the right model choice for a first federated pass here.

``app`` drives the round loop through ``SecAggPlusWorkflow`` rather than a
plain ``FedAvg`` strategy loop: every fund's 17-number update is masked with
pairwise Shamir-shared secrets before this server ever sees it, and the masks
only cancel out in the sum across all funds. This server aggregates; it never
sees an individual fund's contribution. The paired client-side mod
(``secaggplus_mod``) lives in client_app.py — the two must run together.
"""

from __future__ import annotations

from flwr.common import Context, Metrics, ndarrays_to_parameters
from flwr.server import ServerApp, ServerConfig
from flwr.server.compat.legacy_context import LegacyContext
from flwr.server.strategy import FedAvg
from flwr.server.workflow import DefaultWorkflow, SecAggPlusWorkflow
from flwr.serverapp.grid import Grid

from .model import ensure_initialised, get_params, new_model


def _weighted_average(metrics: list[tuple[int, Metrics]]) -> Metrics:
    total = sum(n for n, _ in metrics) or 1
    return {
        "accuracy": sum(n * m["accuracy"] for n, m in metrics) / total,
    }


def _build_strategy(context: Context) -> FedAvg:
    fraction_fit = float(context.run_config.get("fraction-fit", 1.0))
    initial_model = ensure_initialised(new_model())
    initial_parameters = ndarrays_to_parameters(get_params(initial_model))
    return FedAvg(
        fraction_fit=fraction_fit,
        fraction_evaluate=1.0,
        min_available_clients=1,
        evaluate_metrics_aggregation_fn=_weighted_average,
        initial_parameters=initial_parameters,
    )


def _secagg_shares(context: Context, num_funds: int) -> tuple[int, int]:
    """(num_shares, reconstruction_threshold) — sane defaults for a small fund cohort.

    ``num_shares`` = every fund's cohort size, so no fund is excluded from
    masking. ``reconstruction_threshold`` is one less, so the protocol
    tolerates a single fund dropping mid-round without losing the round.
    Both are overridable via run_config for larger deployments.
    """
    default_shares = max(2, num_funds)
    num_shares = int(context.run_config.get("secagg-num-shares", default_shares))
    threshold = int(context.run_config.get("secagg-threshold", max(2, num_shares - 1)))
    return num_shares, threshold


app = ServerApp()


@app.main()
def main(grid: Grid, context: Context) -> None:
    num_rounds = int(context.run_config.get("num-server-rounds", 20))
    num_funds = int(context.run_config.get("num-funds", 8))
    num_shares, threshold = _secagg_shares(context, num_funds)

    legacy_context = LegacyContext(
        context=context,
        config=ServerConfig(num_rounds=num_rounds),
        strategy=_build_strategy(context),
    )

    workflow = DefaultWorkflow(
        fit_workflow=SecAggPlusWorkflow(
            num_shares=num_shares,
            reconstruction_threshold=threshold,
        )
    )
    workflow(grid, legacy_context)
