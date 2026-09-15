"""Prompts for the investment-analyst role.

The whole anti-fabrication posture of this product lives in these strings, so
they are deliberately blunt and repetitive. The model is told, in every prompt:

* it is an analyst assistant, not a source of truth
* it may only use the evidence dossier it is given
* it must never invent funding, customers, revenue, investors, founder
  experience, market numbers or partnerships
* when the evidence is silent it must write exactly "Insufficient public evidence."
* every statement must be labelled FACT / INFERENCE / OPINION / UNKNOWN
"""

from __future__ import annotations

from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..research.evidence_manager import EvidenceManager
from ..scoring.score_config import CRITERIA

INSUFFICIENT = "Insufficient public evidence."

ANALYST_SYSTEM_PROMPT = f"""\
You are an investment analyst assistant supporting a venture capital investor who \
screens early-stage European startups. You are NOT a source of truth. You reason only \
over the evidence dossier supplied in the user message.

ABSOLUTE RULES — violating any of these makes your output worthless:

1. NEVER invent, estimate or "reasonably assume" any of the following:
   funding amounts, investor names, customer names, revenue or ARR figures,
   employee counts, founder experience, market size numbers, partnerships,
   regulatory approvals, growth rates, or valuations.
2. If the dossier does not contain something, write exactly: "{INSUFFICIENT}"
   Do not fill the gap with general knowledge about the sector, and do not fill it
   with what companies "typically" have.
3. Label every substantive statement you make with one of:
   FACT      — stated in the dossier, with a source
   INFERENCE — your reasoning from dossier content, clearly derived
   OPINION   — your judgement, not derivable from the dossier alone
   UNKNOWN   — the dossier does not say
4. You may not decide eligibility, and you may never recommend investing.
   The strongest recommendation available to you is INVESTIGATE.
5. Prefer "I cannot tell from this evidence" over a confident guess. An analyst who
   flags a gap is useful; an analyst who papers over one is dangerous.
6. Anything in the dossier marked UNVERIFIED or INFERRED is a claim, not a fact.
   Say so when you rely on it.

Write in plain, specific, professional English. No marketing language. No filler.
"""


def _line(label: str, value, status: str | None = None, confidence: float | None = None) -> str:
    if value in (None, "", [], {}):
        return f"- {label}: UNKNOWN"
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(v) for v in value)
    suffix = ""
    if status:
        suffix = f"  [{status}"
        if confidence is not None:
            suffix += f", confidence {confidence:.2f}"
        suffix += "]"
    return f"- {label}: {value}{suffix}"


DOSSIER_FIELDS: list[tuple[str, str]] = [
    ("company_name", "Company"),
    ("website", "Website"),
    ("hq_country", "HQ country"),
    ("city", "City"),
    ("founded_year", "Founded"),
    ("sector", "Sector"),
    ("subsector", "Subsector"),
    ("themes", "Thesis themes matched"),
    ("stage", "Stage"),
    ("total_funding_eur", "Total funding (EUR)"),
    ("last_round_eur", "Last round (EUR)"),
    ("last_round_date", "Last round date"),
    ("investors", "Investors"),
    ("founders", "Founders"),
    ("founder_background", "Founder background"),
    ("product_summary", "What the company does"),
    ("business_model", "Business model"),
    ("customers", "Named customers"),
    ("traction_signals", "Traction signals"),
    ("technology", "Technology"),
    ("technical_moat", "Claimed moat"),
    ("competitors", "Competitors"),
    ("market_size_signal", "Market size signal"),
    ("impact_signal", "Impact signal"),
    ("why_now_signal", "Why-now signal"),
]


def build_dossier(startup: Startup, evidence: EvidenceManager | None = None) -> str:
    """The evidence dossier — the ONLY material the model is allowed to use."""
    lines: list[str] = ["=== EVIDENCE DOSSIER ==="]
    if startup.is_demo:
        lines.append("!! THIS IS FICTIONAL DEMO DATA. Do not treat it as a real company. !!")

    for field_name, label in DOSSIER_FIELDS:
        value = getattr(startup, field_name, None)
        if field_name == "stage":
            value = startup.stage.label if startup.stage.value != "UNKNOWN" else None
        if evidence is not None:
            assessment = evidence.assess(startup, field_name, value)
            lines.append(_line(label, value, assessment.verification_status.value,
                               assessment.confidence))
        else:
            lines.append(_line(label, value))

    if evidence is not None:
        sources = [ev for ev in evidence.for_startup(startup.id) if ev.source_url]
        if sources:
            lines.append("\n=== SOURCES ===")
            seen: set[str] = set()
            for ev in sources:
                if ev.source_url in seen:
                    continue
                seen.add(ev.source_url)
                lines.append(
                    f"- [{ev.id}] {ev.source_url} "
                    f"({ev.source_tier.label if ev.source_tier else 'unknown tier'}, "
                    f"field: {ev.field_name})"
                )

    if startup.red_flags:
        lines.append("\n=== RED FLAGS ALREADY DETECTED DETERMINISTICALLY ===")
        for flag in startup.red_flags:
            lines.append(f"- {flag.code}: {flag.title} — {flag.detail}")

    lines.append("\n=== END OF DOSSIER — anything not above is UNKNOWN ===")
    return "\n".join(lines)


def thesis_block(thesis: InvestmentThesis) -> str:
    return (
        "=== INVESTMENT THESIS ===\n"
        f"- Geography: {thesis.geography_label}\n"
        f"- Stages: {', '.join(sorted(s.label for s in thesis.stages))}\n"
        f"- Maximum total funding: €{thesis.max_total_funding_eur:,.0f}\n"
        f"- Minimum founding year: {thesis.min_founded_year or 'none'}\n"
        f"- Themes: {', '.join(thesis.themes)}\n"
        f"- Desired characteristics: {', '.join(thesis.characteristics)}\n"
        f"- Thesis statement: {thesis.thesis_text}\n"
    )


# --------------------------------------------------------------------------- #
# Task prompts
# --------------------------------------------------------------------------- #

THESIS_FIT_PROMPT = """\
{thesis}

{dossier}

TASK: assess how this company fits the thesis.

Return ONE JSON object:
{{
  "fit_summary": "2-3 sentences. Label each statement FACT/INFERENCE/OPINION/UNKNOWN.",
  "supporting_points": ["each begins with FACT:, INFERENCE: or OPINION:"],
  "tension_points": ["where the company does NOT fit, same labelling"],
  "unknowns": ["what you would need to know to judge fit properly"]
}}
If the dossier is too thin to judge, set fit_summary to "{insufficient}".
"""

CRITERIA_PROMPT = """\
{thesis}

{dossier}

TASK: propose a 0-5 rating for each scoring criterion below, using ONLY the dossier.

{criteria_block}

Rules:
- If the dossier contains no evidence for a criterion, set "rating": null. Do NOT guess.
- "confidence" is 0.0-1.0 and reflects how well-evidenced your rating is, not how sure
  you feel.
- "reasoning" must cite the specific dossier content you used, in one or two sentences.

Return ONE JSON object shaped exactly like:
{{"ratings": {{"<criterion_key>": {{"rating": 0-5 or null, "confidence": 0.0-1.0,
  "reasoning": "...", "claim_type": "FACT|INFERENCE|OPINION|UNKNOWN"}}}}}}
"""

RED_FLAGS_PROMPT = """\
{dossier}

TASK: identify investment risks a careful analyst would raise, beyond the ones already
listed in the dossier. Do not repeat a flag that is already there unless you can add a
specific new detail.

Return ONE JSON object:
{{"red_flags": [{{"title": "short", "detail": "what specifically in the dossier triggers
this", "severity": "INFO|MEDIUM|HIGH", "claim_type": "FACT|INFERENCE|OPINION"}}]}}

If nothing further stands out, return {{"red_flags": []}}. Do not invent risks to seem
thorough.
"""

FOUNDER_QUESTIONS_PROMPT = """\
{dossier}

TASK: write the diligence questions an investor should ask these founders. Focus on the
gaps and contradictions in the dossier, not on generic startup questions. Each question
must be answerable in a 30-minute call.

Return ONE JSON object:
{{"questions": [{{"question": "...", "why_it_matters": "one sentence, tied to a specific
gap in the dossier"}}]}}

Between 5 and 8 questions.
"""

MEMO_PROMPT = """\
{thesis}

{dossier}

=== DETERMINISTIC SCORE ===
{score_block}

TASK: draft the narrative sections of an investment memo. Every section must be grounded
in the dossier. Where the dossier is silent, write exactly "{insufficient}" for that
section — do not pad it.

Return ONE JSON object with exactly these keys, all strings:
{{
  "one_line_thesis": "one sentence: why this company might matter",
  "what_the_company_does": "",
  "problem": "",
  "why_this_problem_matters": "",
  "why_now": "",
  "why_it_fits_the_thesis": "",
  "market_potential": "",
  "founder_market_fit": "",
  "traction": "",
  "technology_and_moat": "",
  "impact": "",
  "competition": "",
  "key_risks": "",
  "missing_information": "what an investor still needs before a real decision"
}}

Prefix substantive sentences with FACT:, INFERENCE:, OPINION: or UNKNOWN: so the reader
can tell them apart at a glance.
"""

LOOM_PROMPT = """\
{thesis}

{dossier}

=== MEMO CONTEXT ===
{memo_block}

TASK: write a spoken script for a 45-60 second video in which a thoughtful candidate for
a VC role explains why they chose this company. It must be spoken English, first person,
and 110-150 words — not a word more.

Follow this structure, one short paragraph each, in order:
1. The company and what it does
2. Why the problem is important
3. Why now
4. Why the company is differentiated
5. Why it fits the fund
6. The main reason you would investigate it
7. One risk or diligence question you would want to answer

Tone: a thoughtful investment candidate thinking out loud. Not marketing copy. Do not
use superlatives. Do not state any number that is not in the dossier. Natural openers
such as "I chose X because...", "What makes this particularly interesting is...",
"The biggest question I would want to investigate is..." are welcome.

Return ONE JSON object: {{"script": "the full spoken script", "word_count": <integer>}}
"""


def criteria_block() -> str:
    lines = []
    for criterion in CRITERIA:
        guide = "; ".join(f"{k}={v}" for k, v in sorted(criterion.rating_guide.items()))
        lines.append(f"- {criterion.key} ({criterion.label}, weight {criterion.weight}): "
                     f"{criterion.question}\n    Rating guide: {guide}")
    return "\n".join(lines)


def score_block(startup: Startup) -> str:
    if not startup.score_breakdown:
        return "No deterministic score has been computed yet."
    lines = [f"Total: {startup.score_breakdown.score_total}/100 "
             f"(only {startup.score_breakdown.assessable_weight:.0f} points were assessable)"]
    for criterion in startup.score_breakdown.criteria:
        lines.append(
            f"- {criterion.label}: {criterion.display_rating} "
            f"(weighted {criterion.weighted_score}/{criterion.weight}) — {criterion.reasoning}"
        )
    return "\n".join(lines)
