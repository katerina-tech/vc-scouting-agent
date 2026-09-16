"""One message in a company's assessment transcript.

The pipeline that scores a company isn't one function — it's a small team of
narrow-purpose agents (evidence, eligibility, scoring, risk, recommendation)
that hand a company to one another, and any of them can override an earlier
one's proposal for a stated reason. ``AgentMessage`` is the audit trail of
that hand-off: not a chat transcript for its own sake, but the proof that a
high score alone was never enough to reach a recommendation.

See src/agents/crew.py for the agents that emit these.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AgentMessage(BaseModel):
    agent: str
    action: str
    summary: str
    detail: str = ""
    #: Name of the agent whose proposal this message overrides/vetoes, if any.
    overrides: str | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_veto(self) -> bool:
        return self.overrides is not None
