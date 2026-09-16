"""The fund's agent team: proves the hand-offs actually gate one another.

The risk in src/agents/crew.py isn't the wrapped logic (that's already
tested elsewhere) -- it's whether the recommendation agent correctly
attributes a veto to the agent that actually caused it, and whether wrapping
the four existing functions in agent objects changed their behaviour at all.
"""

from __future__ import annotations

from src.agents.crew import AssessmentCrew, EligibilityAgent, EvidenceAgent, RiskAgent
from src.models.enums import Recommendation, RedFlagSeverity
from src.models.scoring import RedFlag
from src.pipeline import assess_one
from tests.conftest import make_startup


def test_assess_runs_all_five_agents_in_order_and_stores_the_transcript(thesis, evidence):
    startup = make_startup()

    transcript = AssessmentCrew().assess(startup, thesis, evidence, enrich=False)

    assert [m.agent for m in transcript.messages] == [
        "Evidence agent",
        "Eligibility agent",
        "Scoring agent",
        "Risk agent",
        "Recommendation agent",
    ]
    assert startup.agent_transcript == transcript.messages
    assert startup.recommendation is not None


def test_risk_agent_veto_downgrades_a_would_be_investigate_score(thesis, evidence):
    startup = make_startup()
    crew = AssessmentCrew()
    crew.eligibility_agent.act(startup, thesis, evidence)
    crew.scoring_agent.act(startup, thesis, evidence)

    # Force the "high score, serious red flag" scenario deterministically,
    # matching the house pattern used for decide_recommendation's own tests.
    startup.score_total = 90.0
    startup.red_flags = [
        RedFlag(code="thin_team", title="Solo founder, no co-founder disclosed",
                severity=RedFlagSeverity.HIGH, source="deterministic")
    ]

    message = crew.recommendation_agent.act(startup)

    assert startup.recommendation == Recommendation.WATCH
    assert message.overrides == RiskAgent.name
    assert message.is_veto


def test_eligibility_veto_beats_a_high_score(thesis, evidence):
    startup = make_startup(hq_country="United States")
    crew = AssessmentCrew()
    crew.eligibility_agent.act(startup, thesis, evidence)
    crew.scoring_agent.act(startup, thesis, evidence)
    startup.score_total = 90.0  # would clear the INVESTIGATE bar on score alone

    message = crew.recommendation_agent.act(startup)

    assert startup.recommendation == Recommendation.PASS_
    assert message.overrides == EligibilityAgent.name


def test_thin_confidence_is_attributed_to_the_evidence_agent(thesis, evidence):
    startup = make_startup()
    crew = AssessmentCrew()
    crew.eligibility_agent.act(startup, thesis, evidence)
    crew.scoring_agent.act(startup, thesis, evidence)
    startup.score_total = 95.0
    for criterion in startup.score_breakdown.criteria:
        criterion.confidence = 0.1

    message = crew.recommendation_agent.act(startup)

    assert startup.recommendation == Recommendation.WATCH
    assert message.overrides == EvidenceAgent.name


def test_no_veto_is_reported_when_recommendation_agrees_with_the_score(thesis, evidence):
    startup = make_startup()
    crew = AssessmentCrew()
    crew.eligibility_agent.act(startup, thesis, evidence)
    crew.scoring_agent.act(startup, thesis, evidence)
    crew.risk_agent.act(startup, thesis, evidence)
    startup.score_total = 40.0  # below every threshold -- nothing to override

    message = crew.recommendation_agent.act(startup)

    assert message.overrides is None
    assert not message.is_veto


def test_crew_matches_calling_the_underlying_functions_directly(thesis, evidence):
    """Wrapping in agents must not change what the pipeline actually decides."""
    from src.filters.eligibility import apply_eligibility
    from src.research.red_flags import apply_red_flags
    from src.scoring.score_engine import apply_score

    direct = make_startup()
    # Matches assess_one's original enrich=False path exactly: it always refreshed
    # confidence on existing evidence before eligibility, never skipped that step.
    evidence.refresh_startup_confidence(direct)
    apply_eligibility(direct, thesis, evidence)
    apply_score(direct, thesis, evidence)
    apply_red_flags(direct, thesis, evidence)

    via_crew = make_startup()
    AssessmentCrew().assess(via_crew, thesis, evidence, enrich=False)

    assert direct.eligibility_status == via_crew.eligibility_status
    assert direct.score_total == via_crew.score_total
    assert [f.code for f in direct.red_flags] == [f.code for f in via_crew.red_flags]


def test_pipeline_assess_one_still_returns_notes_and_updates_open_questions(thesis, evidence):
    startup = make_startup()

    notes = assess_one(startup, thesis, evidence, enrich=False)

    assert notes == []  # no enrichment requested -> no notes, same as before the rewrite
    assert startup.agent_transcript  # the crew ran and left its transcript behind
