"""The Flower ClientApp: one instance per fund, each with its own private data.

A fund's ``X``/``y`` never leaves this object — only the fitted model's 17
numbers (``get_parameters``) go to the server, and that's the whole point of
using Flower here instead of just pooling every fund's SQLite file.

Two data sources are supported via ``context.node_config``:
  * ``fund-index`` (int)  -> a synthetic fund from partition.py (demo/tests)
  * ``db-path``    (str)  -> a real fund's own vc_scouting.db

``app`` runs the SecAgg+ protocol (``secaggplus_mod``): the 17 numbers this
client returns from ``fit`` never reach the server in the clear — they're
masked with pairwise, Shamir-shared secrets that only cancel out once every
fund's masked update is summed together. The server literally cannot recover
one fund's individual contribution, only the aggregate. This mod must be
paired with ``SecAggPlusWorkflow`` on the server side (see server_app.py) —
one without the other fails the handshake, it isn't optional per side.
"""

from __future__ import annotations

import numpy as np
from flwr.client import ClientApp, NumPyClient
from flwr.client.mod import secaggplus_mod
from flwr.common import Context
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import log_loss

from ..storage.repository import Repository
from .features import build_dataset
from .model import ensure_initialised, get_params, new_model, set_params
from .partition import make_synthetic_market


class FundClient(NumPyClient):
    """Local training/evaluation for a single fund's private deal flow."""

    def __init__(self, fund_id: str, X: np.ndarray, y: np.ndarray) -> None:
        self.fund_id = fund_id
        self.X, self.y = X, y
        self.model = ensure_initialised(new_model())

    def get_parameters(self, config):  # noqa: ANN001, D102 — Flower's signature
        return get_params(self.model)

    def fit(self, parameters, config):
        set_params(self.model, parameters)
        if len(np.unique(self.y)) >= 2:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", ConvergenceWarning)
                self.model.fit(self.X, self.y)
        return get_params(self.model), len(self.X), {"fund_id": self.fund_id}

    def evaluate(self, parameters, config):
        set_params(self.model, parameters)
        probs = self.model.predict_proba(self.X)
        loss = float(log_loss(self.y, probs, labels=[0, 1]))
        accuracy = float(((probs[:, 1] >= 0.5).astype(int) == self.y).mean())
        return loss, len(self.X), {"accuracy": accuracy, "fund_id": self.fund_id}


def _load_local_fund_data(db_path: str) -> tuple[np.ndarray, np.ndarray]:
    repo = Repository(db_path=db_path)
    return build_dataset(repo.list_startups())


def client_fn(context: Context):
    node_config = context.node_config

    if "db-path" in node_config:
        fund_id = str(node_config["db-path"])
        X, y = _load_local_fund_data(fund_id)
    else:
        fund_index = int(node_config.get("fund-index", context.node_id % 8))
        num_funds = int(node_config.get("num-funds", 8))
        n_per_fund = int(node_config.get("n-companies-per-fund", 40))
        seed = int(node_config.get("seed", 42))
        funds, _ = make_synthetic_market(num_funds=num_funds, n_companies_per_fund=n_per_fund, seed=seed)
        partition = funds[fund_index % len(funds)]
        fund_id, X, y = partition.fund_id, partition.X, partition.y

    return FundClient(fund_id, X, y).to_client()


app = ClientApp(client_fn=client_fn, mods=[secaggplus_mod])
