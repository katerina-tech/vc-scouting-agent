"""The fund's agent team: narrow-purpose agents that hand a company to one
another, any of which can override an earlier agent's proposal for a stated
reason. See crew.py for the agents and AssessmentCrew, the orchestrator.

This is one half of the project's two-layer collaboration story. Inside a
fund, this team of agents keeps each other honest — a strong score alone
can't reach a recommendation if the risk agent still has an open concern.
Across funds, src/federated/ lets each fund's *scoring agent* — not the fund
itself — safely align its judgement with every other fund's, via Flower,
without a single evaluated company ever leaving the fund that scored it.
"""
