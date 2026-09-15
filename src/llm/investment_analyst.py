"""The investment-analyst facade.

Every function here follows the same shape:

    result = analyst.some_analysis(startup, ...)
    result.available  -> did the LLM actually produce something?
    result.data       -> validated, typed payload
    result.fallback   -> deterministic text used when it did not

Nothing in the application calls the LLM directly, and nothing breaks when the
LLM is off. The deterministic fallback is not a degraded error path — it is the
default mode of the product.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from ..models.enums import ClaimType, RedFlagSeverity
from ..models.scoring import RedFlag
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..research.evidence_manager import EvidenceManager
from ..research.red_flags import open_questions_from_flags
from ..scoring.score_config import CRITERIA_BY_KEY
from .client import LLMClient, LLMResponse, LLMUsage, NullLLMClient, get_llm_client
from .prompts import (
    ANALYST_SYSTEM_PROMPT,
    CRITERIA_PROMPT,
    FOUNDER_QUESTIONS_PROMPT,
    INSUFFICIENT,
    LOOM_PROMPT,
    MEMO_PROMPT,
    RED_FLAGS_PROMPT,
    THESIS_FIT_PROMPT,
    build_dossier,
    criteria_block,
    score_block,
    thesis_block,
)


@dataclass
class AnalysisResult:
    """What every analyst call returns."""

    available: bool
    data: Any = None
    note: str = ""
    usage: dict = field(default_factory=dict)

    @property
    def used_llm(self) -> bool:
        return self.available


# --------------------------------------------------------------------------- #
# Validation schemas — the LLM's output is never trusted raw
# --------------------------------------------------------------------------- #

class CriterionProposal(BaseModel):
    rating: int | None = Field(default=None, ge=0, le=5)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""
    claim_type: ClaimType = ClaimType.INFERENCE


class CriteriaProposals(BaseModel):
    ratings: dict[str, CriterionProposal] = Field(default_factory=dict)


class ThesisFitAnalysis(BaseModel):
    fit_summary: str = INSUFFICIENT
    supporting_points: list[str] = Field(default_factory=list)
    tension_points: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class LLMRedFlag(BaseModel):
    title: str
    detail: str = ""
    severity: RedFlagSeverity = RedFlagSeverity.MEDIUM
    claim_type: ClaimType = ClaimType.INFERENCE


class LLMRedFlags(BaseModel):
    red_flags: list[LLMRedFlag] = Field(default_factory=list)


class FounderQuestion(BaseModel):
    question: str
    why_it_matters: str = ""


class FounderQuestions(BaseModel):
    questions: list[FounderQuestion] = Field(default_factory=list)


class MemoSections(BaseModel):
    one_line_thesis: str = INSUFFICIENT
    what_the_company_does: str = INSUFFICIENT
    problem: str = INSUFFICIENT
    why_this_problem_matters: str = INSUFFICIENT
    why_now: str = INSUFFICIENT
    why_it_fits_the_thesis: str = INSUFFICIENT
    market_potential: str = INSUFFICIENT
    founder_market_fit: str = INSUFFICIENT
    traction: str = INSUFFICIENT
    technology_and_moat: str = INSUFFICIENT
    impact: str = INSUFFICIENT
    competition: str = INSUFFICIENT
    key_risks: str = INSUFFICIENT
    missing_information: str = INSUFFICIENT


class LoomScript(BaseModel):
    script: str = ""
    word_count: int = 0


# --------------------------------------------------------------------------- #
# The analyst
# --------------------------------------------------------------------------- #

class InvestmentAnalyst:
    """Thin, defensive wrapper around the LLM for investment-analysis tasks."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_llm_client()
        self.usage = LLMUsage()
        self.last_error: str = ""

    @property
    def available(self) -> bool:
        return self.client.available

    def describe(self) -> str:
        return self.client.describe()

    # ------------------------------------------------------------- plumbing
    def _call(self, user_prompt: str, *, max_tokens: int | None = None) -> LLMResponse:
        response = self.client.complete(
            ANALYST_SYSTEM_PROMPT, user_prompt, json_mode=True, max_tokens=max_tokens
        )
        if response.usage:
            self.usage.add(response.usage)
        if not response.ok:
            self.last_error = response.error
        return response

    def _validate(self, response: LLMResponse, model: type[BaseModel]) -> BaseModel | None:
        if not response.ok or response.data is None:
            return None
        try:
            return model.model_validate(response.data)
        except ValidationError as exc:
            self.last_error = f"The model returned JSON that did not match the schema: {exc}"
            return None

    # ------------------------------------------------------------ analyses
    def thesis_fit(
        self, startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager | None = None
    ) -> AnalysisResult:
        if not self.available:
            return AnalysisResult(False, _fallback_thesis_fit(startup, thesis),
                                  note=self.describe())
        prompt = THESIS_FIT_PROMPT.format(
            thesis=thesis_block(thesis),
            dossier=build_dossier(startup, evidence),
            insufficient=INSUFFICIENT,
        )
        parsed = self._validate(self._call(prompt, max_tokens=900), ThesisFitAnalysis)
        if parsed is None:
            return AnalysisResult(False, _fallback_thesis_fit(startup, thesis),
                                  note=self.last_error)
        return AnalysisResult(True, parsed, usage=self.client.usage.__dict__ if hasattr(self.client, "usage") else {})

    def propose_criteria_ratings(
        self, startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager | None = None
    ) -> AnalysisResult:
        if not self.available:
            return AnalysisResult(False, {}, note=self.describe())
        prompt = CRITERIA_PROMPT.format(
            thesis=thesis_block(thesis),
            dossier=build_dossier(startup, evidence),
            criteria_block=criteria_block(),
        )
        parsed = self._validate(self._call(prompt, max_tokens=1800), CriteriaProposals)
        if parsed is None:
            return AnalysisResult(False, {}, note=self.last_error)

        clean: dict[str, dict] = {}
        for key, proposal in parsed.ratings.items():  # type: ignore[union-attr]
            if key not in CRITERIA_BY_KEY:
                continue  # silently drop invented criteria
            clean[key] = {
                "rating": proposal.rating,
                "confidence": proposal.confidence,
                "reasoning": proposal.reasoning,
                "claim_type": proposal.claim_type.value,
            }
        return AnalysisResult(True, clean)

    def extra_red_flags(
        self, startup: Startup, evidence: EvidenceManager | None = None
    ) -> AnalysisResult:
        if not self.available:
            return AnalysisResult(False, [], note=self.describe())
        prompt = RED_FLAGS_PROMPT.format(dossier=build_dossier(startup, evidence))
        parsed = self._validate(self._call(prompt, max_tokens=1000), LLMRedFlags)
        if parsed is None:
            return AnalysisResult(False, [], note=self.last_error)

        existing = {f.title.strip().lower() for f in startup.red_flags}
        flags = [
            RedFlag(
                code=f"llm_{abs(hash(f.title)) % 10**8}",
                title=f.title.strip(),
                detail=f"[{f.claim_type.value}] {f.detail.strip()}",
                severity=f.severity,
                source="llm",
            )
            for f in parsed.red_flags  # type: ignore[union-attr]
            if f.title.strip().lower() not in existing
        ]
        return AnalysisResult(True, flags)

    def founder_questions(
        self, startup: Startup, evidence: EvidenceManager | None = None
    ) -> AnalysisResult:
        if not self.available:
            return AnalysisResult(False, _fallback_questions(startup), note=self.describe())
        prompt = FOUNDER_QUESTIONS_PROMPT.format(dossier=build_dossier(startup, evidence))
        parsed = self._validate(self._call(prompt, max_tokens=1200), FounderQuestions)
        if parsed is None:
            return AnalysisResult(False, _fallback_questions(startup), note=self.last_error)
        return AnalysisResult(
            True,
            [f"{q.question} — {q.why_it_matters}" if q.why_it_matters else q.question
             for q in parsed.questions],  # type: ignore[union-attr]
        )

    def memo_sections(
        self, startup: Startup, thesis: InvestmentThesis, evidence: EvidenceManager | None = None
    ) -> AnalysisResult:
        if not self.available:
            return AnalysisResult(False, None, note=self.describe())
        prompt = MEMO_PROMPT.format(
            thesis=thesis_block(thesis),
            dossier=build_dossier(startup, evidence),
            score_block=score_block(startup),
            insufficient=INSUFFICIENT,
        )
        parsed = self._validate(self._call(prompt, max_tokens=2600), MemoSections)
        if parsed is None:
            return AnalysisResult(False, None, note=self.last_error)
        return AnalysisResult(True, parsed)

    def loom_script(
        self,
        startup: Startup,
        thesis: InvestmentThesis,
        memo_text: str,
        evidence: EvidenceManager | None = None,
    ) -> AnalysisResult:
        if not self.available:
            return AnalysisResult(False, None, note=self.describe())
        prompt = LOOM_PROMPT.format(
            thesis=thesis_block(thesis),
            dossier=build_dossier(startup, evidence),
            memo_block=memo_text[:4000],
        )
        parsed = self._validate(self._call(prompt, max_tokens=800), LoomScript)
        if parsed is None or not getattr(parsed, "script", "").strip():
            return AnalysisResult(False, None, note=self.last_error)
        return AnalysisResult(True, parsed)


# --------------------------------------------------------------------------- #
# Deterministic fallbacks — used whenever the LLM is off or fails
# --------------------------------------------------------------------------- #

def _fallback_thesis_fit(startup: Startup, thesis: InvestmentThesis) -> ThesisFitAnalysis:
    supporting: list[str] = []
    tensions: list[str] = []
    unknowns: list[str] = []

    if startup.hq_country:
        target = supporting if startup.hq_country in thesis.geographies else tensions
        target.append(f"FACT: headquartered in {startup.hq_country}.")
    else:
        unknowns.append("Headquarters country is not recorded.")

    if startup.stage.value != "UNKNOWN":
        target = supporting if startup.stage in thesis.stages else tensions
        target.append(f"FACT: stage recorded as {startup.stage.label}.")
    else:
        unknowns.append("Funding stage is not recorded.")

    if startup.total_funding_eur is None:
        unknowns.append("Total funding could not be verified, so the ceiling test is unresolved.")
    elif startup.total_funding_eur < thesis.max_total_funding_eur:
        supporting.append(
            f"FACT: €{startup.total_funding_eur:,.0f} total funding is below the "
            f"€{thesis.max_total_funding_eur:,.0f} ceiling."
        )
    else:
        tensions.append(
            f"FACT: €{startup.total_funding_eur:,.0f} raised exceeds the thesis ceiling."
        )

    if startup.themes:
        matched = [t for t in startup.themes if t.lower() in {x.lower() for x in thesis.themes}]
        if matched:
            supporting.append(f"INFERENCE: maps to thesis theme(s) {', '.join(matched)}.")
        else:
            tensions.append(f"INFERENCE: themes found ({', '.join(startup.themes)}) are off-thesis.")
    else:
        unknowns.append("No thesis theme could be derived from the available text.")

    if supporting and not tensions:
        summary = (
            f"{startup.company_name} matches the thesis on every dimension that could be "
            f"checked ({len(supporting)} of {len(supporting) + len(unknowns)})."
        )
    elif supporting:
        summary = (
            f"{startup.company_name} partially matches the thesis: "
            f"{len(supporting)} dimension(s) fit, {len(tensions)} do not."
        )
    else:
        summary = INSUFFICIENT

    return ThesisFitAnalysis(
        fit_summary=summary,
        supporting_points=supporting,
        tension_points=tensions,
        unknowns=unknowns,
    )


def _fallback_questions(startup: Startup) -> list[str]:
    questions = open_questions_from_flags(startup)
    baseline = [
        "What does your next 12 months look like, and what would you use this round for?",
        "Who are your three closest competitors and what do you do that they cannot?",
        "What is the single assumption that, if wrong, breaks the business?",
    ]
    for q in baseline:
        if q not in questions:
            questions.append(q)
    return questions[:8]


def make_analyst(client: LLMClient | None = None) -> InvestmentAnalyst:
    return InvestmentAnalyst(client or get_llm_client())


def offline_analyst() -> InvestmentAnalyst:
    """Explicitly deterministic analyst — used in tests."""
    return InvestmentAnalyst(NullLLMClient("Offline analyst (tests)."))
