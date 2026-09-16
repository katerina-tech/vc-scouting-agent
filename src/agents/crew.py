"""Five narrow-purpose agents and the crew that runs them in sequence.

Each agent wraps one existing, independently-tested piece of logic
(enrichment, eligibility, scoring, red flags, recommendation) -- this module
adds no new business rules. What it adds is the hand-off: every agent emits
an ``AgentMessage`` stating what it did and why, and the recommendation agent
can only reach INVESTIGATE if none of the agents before it raised an
objection. When one does, the message says so explicitly -- ``overrides``
names the agent whose proposal got downgraded, and that is what makes this a
team with veto power rather than five functions called in a row.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..enrichment.company_enrichment import enrich_company
from ..filters.eligibility import apply_eligibility
from ..models.agents import AgentMessage
from ..models.enums import EligibilityStatus, Recommendation, RedFlagSeverity
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..reports.investment_memo import decide_recommendation
from ..research.evidence_manager import EvidenceManager
from ..research.red_flags import apply_red_flags
from ..scoring.score_config import (
    MIN_COVERAGE_FOR_INVESTIGATE,
    MIN_CONFIDENCE_FOR_INVESTIGATE,
    RECOMMENDATION_THRESHOLDS,
)
from ..scoring.score_engine import apply_score


@dataclass
class AssessmentTranscript:
    """One company's full agent-team conversation for its latest assessment."""

    startup_id: str
    messages: list[AgentMessage] = field(default_factory=list)
    #: Raw, detailed enrichment notes (shown in the "signals extracted" panel) --
    #: kept separate from the evidence agent's one-line summary message.
    notes: list[str] = field(default_factory=list)

    @property
    def vetoes(self) -> list[AgentMessage]:
        return [m for m in self.messages if m.is_veto]


class EvidenceAgent:
    """Gathers and confirms what is actually known about the company."""

    name = "Evidence agent"

    def act(
        self, startup: Startup, evidence: EvidenceManager, *, enrich: bool
    ) -> tuple[AgentMessage, list[str]]:
        if enrich:
            notes = enrich_company(startup, evidence)
            summary = f"Gathered evidence ({len(notes)} new note(s))." if notes else "No new evidence found."
        else:
            evidence.refresh_startup_confidence(startup)
            notes = []
            summary = "Refreshed confidence on existing evidence; did not fetch anything new."
        return AgentMessage(agent=self.name, action="gather evidence", summary=summary), notes


class EligibilityAgent:
    """The hard gate: geography, stage, funding ceiling, themes, activity."""

    name = "Eligibility agent"

    def act(self, startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager) -> AgentMessage:
        apply_eligibility(startup, thesis, evidence)
        status = startup.eligibility_status
        if status == EligibilityStatus.INELIGIBLE:
            reasons = "; ".join(startup.eligibility_reasons) or "does not match the thesis"
            return AgentMessage(
                agent=self.name, action="check eligibility",
                summary="Ruled out on hard filters -- scoring below still runs, but cannot recommend it.",
                detail=reasons,
            )
        label = status.value.replace("_", " ").title()
        return AgentMessage(agent=self.name, action="check eligibility", summary=f"Eligibility: {label}.")


class ScoringAgent:
    """Rates the 8 criteria against the evidence the evidence agent confirmed."""

    name = "Scoring agent"

    def act(self, startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager) -> AgentMessage:
        apply_score(startup, thesis, evidence)
        breakdown = startup.score_breakdown
        if startup.score_total is None or breakdown is None:
            return AgentMessage(agent=self.name, action="score", summary="Could not compute a score yet.")
        return AgentMessage(
            agent=self.name, action="score",
            summary=f"Proposes {startup.score_total:.0f}/100 "
                    f"({breakdown.evidence_coverage:.0%} of the framework assessable).",
        )


class RiskAgent:
    """Audits for red flags the score alone wouldn't catch."""

    name = "Risk agent"

    def act(self, startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager) -> AgentMessage:
        apply_red_flags(startup, thesis, evidence)
        active = [f for f in startup.red_flags if not f.dismissed_by_human]
        if not active:
            return AgentMessage(agent=self.name, action="audit for risk", summary="No open red flags.")
        high = [f for f in active if f.severity == RedFlagSeverity.HIGH]
        titles = ", ".join(f.title for f in active[:3])
        severity = "high-severity" if high else "medium-severity"
        return AgentMessage(
            agent=self.name, action="audit for risk",
            summary=f"{len(active)} open {severity} flag(s): {titles}.",
        )


class RecommendationAgent:
    """The final gate. Only reaches INVESTIGATE if nobody upstream objected."""

    name = "Recommendation agent"

    def act(self, startup: Startup) -> AgentMessage:
        recommendation, reason = decide_recommendation(startup)
        startup.recommendation = recommendation
        vetoed_by = self._attribute_veto(startup, recommendation)
        return AgentMessage(
            agent=self.name, action="decide",
            summary=f"Recommendation: {recommendation.label}.",
            detail=reason,
            overrides=vetoed_by,
        )

    @staticmethod
    def _attribute_veto(startup: Startup, recommendation: Recommendation) -> str | None:
        """Which agent's objection kept a would-be INVESTIGATE from landing there.

        Mirrors ``decide_recommendation``'s own branch order -- this never makes
        the decision, it only explains one that was already made, for the
        transcript. A high score reaching a lower recommendation without one
        of these conditions would mean decide_recommendation changed underneath
        this function; the tests catch that.
        """
        score = startup.score_total
        if score is None or score < RECOMMENDATION_THRESHOLDS["investigate"]:
            return None
        if recommendation == Recommendation.INVESTIGATE:
            return None

        if startup.eligibility_status == EligibilityStatus.INELIGIBLE:
            return EligibilityAgent.name

        active = [f for f in startup.red_flags if not f.dismissed_by_human]
        if any(f.severity == RedFlagSeverity.HIGH for f in active):
            return RiskAgent.name
        if len([f for f in active if f.severity == RedFlagSeverity.MEDIUM]) >= 3:
            return RiskAgent.name

        breakdown = startup.score_breakdown
        if breakdown is not None and breakdown.evidence_coverage < MIN_COVERAGE_FOR_INVESTIGATE:
            return EvidenceAgent.name
        if breakdown is not None and breakdown.confidence < MIN_CONFIDENCE_FOR_INVESTIGATE:
            return EvidenceAgent.name
        return None


class AssessmentCrew:
    """Coordinates the fund's agent team for one company, with an auditable transcript."""

    def __init__(self) -> None:
        self.evidence_agent = EvidenceAgent()
        self.eligibility_agent = EligibilityAgent()
        self.scoring_agent = ScoringAgent()
        self.risk_agent = RiskAgent()
        self.recommendation_agent = RecommendationAgent()

    def assess(
        self,
        startup: Startup,
        thesis: InvestmentThesis,
        evidence: EvidenceManager,
        *,
        enrich: bool = True,
    ) -> AssessmentTranscript:
        transcript = AssessmentTranscript(startup_id=startup.id)
        evidence_message, notes = self.evidence_agent.act(startup, evidence, enrich=enrich)
        transcript.messages.append(evidence_message)
        transcript.notes = notes
        transcript.messages.append(self.eligibility_agent.act(startup, thesis, evidence))
        transcript.messages.append(self.scoring_agent.act(startup, thesis, evidence))
        transcript.messages.append(self.risk_agent.act(startup, thesis, evidence))
        transcript.messages.append(self.recommendation_agent.act(startup))
        startup.agent_transcript = list(transcript.messages)
        return transcript
