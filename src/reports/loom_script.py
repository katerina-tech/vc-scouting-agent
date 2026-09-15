"""Loom application-script generation.

A 45-60 second spoken pitch explaining why *this candidate* would investigate
*this company*. Target length is derived from an average speaking rate of about
150 words per minute, so 110-150 words lands in the window.

The deterministic version is not a placeholder — it is a real, speakable script
assembled from the evidence, and it never states a number that is not in the
record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..llm.investment_analyst import InvestmentAnalyst, LoomScript
from ..models.startup import Startup
from ..models.thesis import InvestmentThesis
from ..research.evidence_manager import EvidenceManager

WORDS_PER_MINUTE = 150
TARGET_MIN_WORDS = 110
TARGET_MAX_WORDS = 150

STRUCTURE: list[str] = [
    "Company and what it does",
    "Why the problem is important",
    "Why now",
    "Why the company is differentiated",
    "Why it fits the fund",
    "Main reason I would investigate it",
    "One risk / diligence question",
]


@dataclass
class LoomPitch:
    startup_id: str
    company: str
    script: str
    word_count: int = 0
    estimated_seconds: int = 0
    llm_used: bool = False
    is_demo: bool = False
    warnings: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def within_target(self) -> bool:
        return 45 <= self.estimated_seconds <= 60

    def to_markdown(self) -> str:
        header = f"# Loom script — {self.company}\n"
        if self.is_demo:
            header = "> ⚠️ **DEMO DATA — fictional company.**\n\n" + header
        meta = (
            f"*{self.word_count} words · ~{self.estimated_seconds}s spoken · "
            f"{'LLM-assisted' if self.llm_used else 'deterministic'}*\n"
        )
        warn = ""
        if self.warnings:
            warn = "\n".join(f"> ⚠️ {w}" for w in self.warnings) + "\n"
        return f"{header}\n{meta}\n{warn}\n{self.script}\n"


def count_words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if w])


def estimate_seconds(word_count: int) -> int:
    return round(word_count / WORDS_PER_MINUTE * 60)


def _sentence(text: str | None, max_chars: int = 150) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rsplit(" ", 1)[0]
    return cleaned


def _lead(text: str) -> str:
    """Lower-case a clause so it reads mid-sentence — but never wreck an acronym.

    ``"CSRD comes into force"`` must stay ``"CSRD comes into force"``, not
    ``"csrd comes into force"``.
    """
    if not text:
        return ""
    first, _, rest = text.partition(" ")
    if first.isupper() and len(first) > 1:
        return text
    return first[:1].lower() + first[1:] + (" " + rest if rest else "")


def _deterministic_script(startup: Startup, thesis: InvestmentThesis) -> tuple[str, list[str]]:
    warnings: list[str] = []
    parts: list[str] = []

    # 1. Company and what it does
    what = _sentence(startup.product_summary, 120)
    if what:
        parts.append(
            f"I chose {startup.company_name}, a {startup.stage.label.lower()} company in "
            f"{startup.hq_country or 'Europe'} building {_lead(what)}."
        )
    else:
        parts.append(
            f"I chose {startup.company_name}, a {startup.stage.label.lower()} "
            f"{(startup.sector or 'technology').lower()} company in "
            f"{startup.hq_country or 'Europe'}."
        )
        warnings.append("No product description was available, so the opening is thin.")

    # 2. Why the problem matters
    problem = _sentence(startup.market_size_signal or startup.impact_signal, 120)
    if problem:
        parts.append(
            f"The problem matters because of the scale behind it — {_lead(problem)}."
        )
    else:
        parts.append(
            "What I could not establish from public sources is how large the underlying "
            "problem is, and that is the first thing I would want to size."
        )
        warnings.append("No market-size or impact signal — the 'why it matters' beat is weak.")

    # 3. Why now
    why_now = _sentence(startup.why_now_signal, 130)
    if why_now:
        parts.append(f"The timing is interesting: {_lead(why_now)}.")
    else:
        parts.append("I could not find a clear external reason why this has to happen now.")
        warnings.append("No why-now signal available.")

    # 4. Differentiation
    moat = _sentence(startup.technical_moat or startup.technology, 130)
    if moat:
        parts.append(f"What makes the opportunity particularly interesting is {_lead(moat)}.")
    else:
        parts.append("Their differentiation is not visible from public material, which is itself a finding.")

    # 5. Fit with the fund
    fit_bits = []
    if startup.hq_country:
        fit_bits.append(startup.hq_country)
    if startup.stage.value != "UNKNOWN":
        fit_bits.append(startup.stage.label.lower())
    if startup.total_funding_eur is not None:
        fit_bits.append(f"under €{thesis.max_total_funding_eur/1_000_000:.0f} million raised")
    themes = ", ".join(startup.themes) if startup.themes else None
    parts.append(
        "The reason I think this is relevant for our thesis is that it is "
        + ", ".join(fit_bits or ["within our stated scope"])
        + (f", squarely in {themes}." if themes else ".")
    )

    # 6. Main reason to investigate
    if startup.customers:
        parts.append(
            f"The main reason I would investigate is that they already have named customers "
            f"including {startup.customers[0]}."
        )
    elif startup.traction_signals:
        parts.append(
            f"The main reason I would investigate is the traction they claim: "
            f"{_lead(_sentence(startup.traction_signals[0], 90))}."
        )
    else:
        parts.append(
            "The main reason I would investigate is the thesis fit rather than the traction, "
            "because there is no commercial evidence yet."
        )

    # 7. Risk / diligence question
    question = startup.open_questions[0] if startup.open_questions else (
        "What would stop a well-funded competitor replicating this within a year?"
    )
    parts.append(f"The biggest question I would want to investigate is: {question}")

    return " ".join(parts), warnings


def _trim_to_target(script: str) -> tuple[str, list[str]]:
    """Keep the script inside the 45-60 second window where possible."""
    warnings: list[str] = []
    words = count_words(script)
    if words <= TARGET_MAX_WORDS:
        if words < TARGET_MIN_WORDS:
            warnings.append(
                f"Only {words} words (~{estimate_seconds(words)}s). Thin evidence made a "
                "fuller script impossible — add detail before recording."
            )
        return script, warnings

    # Drop whole sentences from the middle rather than cutting mid-thought.
    sentences = re.split(r"(?<=[.!?])\s+", script.strip())
    while count_words(" ".join(sentences)) > TARGET_MAX_WORDS and len(sentences) > 4:
        # Remove the longest non-essential sentence (never the first or last).
        middle = sentences[1:-1]
        longest = max(middle, key=count_words)
        sentences.remove(longest)
    trimmed = " ".join(sentences)
    if count_words(trimmed) > TARGET_MAX_WORDS:
        warnings.append(
            f"Script is {count_words(trimmed)} words (~{estimate_seconds(count_words(trimmed))}s) — "
            "slightly over 60 seconds. Trim by hand before recording."
        )
    return trimmed, warnings


def generate_loom_script(
    startup: Startup,
    thesis: InvestmentThesis,
    evidence: EvidenceManager | None = None,
    analyst: InvestmentAnalyst | None = None,
    memo_text: str = "",
) -> LoomPitch:
    """Produce a speakable 45-60 second pitch for one shortlisted company."""
    script, warnings = _deterministic_script(startup, thesis)
    llm_used = False

    if analyst is not None and analyst.available:
        result = analyst.loom_script(startup, thesis, memo_text or "", evidence)
        if result.available and isinstance(result.data, LoomScript):
            candidate = result.data.script.strip()
            if candidate and count_words(candidate) >= 60:
                script = candidate
                llm_used = True
                warnings = []
            else:
                warnings.append(
                    "The analyst model returned an unusably short script; using the "
                    "deterministic version instead."
                )
        else:
            warnings.append(f"LLM script unavailable ({result.note}).")

    script, trim_warnings = _trim_to_target(script)
    warnings.extend(trim_warnings)

    words = count_words(script)
    return LoomPitch(
        startup_id=startup.id,
        company=startup.company_name,
        script=script,
        word_count=words,
        estimated_seconds=estimate_seconds(words),
        llm_used=llm_used,
        is_demo=startup.is_demo,
        warnings=warnings,
    )


def structure_checklist() -> list[str]:
    return list(STRUCTURE)
