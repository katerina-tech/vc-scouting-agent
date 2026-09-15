"""Technology and defensibility signals.

Looks for the concrete, checkable markers of a moat — proprietary data, patents,
hardware, regulatory approval, deep integrations, switching costs — and equally
for the markers of *no* moat: thin GPT wrappers, pure services work.
"""

from __future__ import annotations

import re

from ..models.enums import SourceType, VerificationStatus
from ..models.startup import Startup
from ..research.evidence_manager import EvidenceManager

#: Marker -> how much it can support a defensibility claim.
MOAT_MARKERS: dict[str, str] = {
    r"\bpatent(?:ed|s| pending| portfolio)?\b": "patent or patent application referenced",
    r"\bproprietary (?:data|dataset|database|model|algorithm|process)\b": "proprietary data or model claimed",
    r"\b(?:in-house|own) (?:hardware|sensor|device|instrument)\b": "own hardware or sensing",
    r"\bce mark|fda clearance|regulatory approval|medical device class\b": "regulatory approval as a barrier",
    r"\b(?:deep|native) integration(?:s)? with\b": "deep integrations creating switching costs",
    r"\bswitching cost|system of record|workflow integration\b": "workflow lock-in claimed",
    r"\bnetwork effect|two-sided marketplace|data flywheel\b": "network or data flywheel claimed",
    r"\b(?:exclusive|long-term) (?:partnership|licence|license|agreement) with\b": "exclusive partnership claimed",
    r"\bpublished in (?:nature|science|the lancet|nejm)|peer-reviewed\b": "peer-reviewed validation",
}

WEAK_MARKERS: dict[str, str] = {
    r"\b(?:built|powered) (?:on|with) (?:chatgpt|gpt-4|gpt-5|openai api)\b":
        "thin LLM-wrapper language — differentiation unclear",
    r"\bconsult(?:ing|ancy)\b": "consulting language present — check whether revenue is really recurring",
    r"\bbespoke (?:projects|implementations|engagements)\b": "bespoke project work — limits scalability",
    r"\bno[- ]code (?:template|wrapper)\b": "assembled from no-code components",
}

SCALABILITY_POSITIVE = re.compile(
    r"\b(saas|subscription|api|self-serve|platform|per-seat|usage-based|multi-tenant|"
    r"marketplace|licen[cs]e fee)\b", re.IGNORECASE,
)
SCALABILITY_NEGATIVE = re.compile(
    r"\b(consulting|agency|bespoke|per-project|day rate|installation service|"
    r"managed service|systems integrator)\b", re.IGNORECASE,
)


def extract_technology_signals(
    startup: Startup, corpus: str, evidence: EvidenceManager, source_url: str | None = None
) -> list[str]:
    notes: list[str] = []
    text = " ".join(
        p for p in [corpus, startup.technology, startup.technical_moat, startup.business_model] if p
    )
    if not text.strip():
        return notes

    strong = [desc for pattern, desc in MOAT_MARKERS.items() if re.search(pattern, text, re.IGNORECASE)]
    weak = [desc for pattern, desc in WEAK_MARKERS.items() if re.search(pattern, text, re.IGNORECASE)]

    if strong:
        summary = "; ".join(strong)
        if not startup.technical_moat:
            startup.technical_moat = summary
        evidence.record(
            startup.id, "technical_moat", summary,
            source_url=source_url, source_title="Defensibility markers in text",
            source_type=SourceType.COMPANY_WEBSITE if source_url else SourceType.LLM_INFERENCE,
            verification_status=VerificationStatus.INFERRED,
            note=(
                "Defensibility markers claimed in the company's own material. A patent claim "
                "should be checked in EPO/WIPO; a regulatory claim in the relevant registry."
            ),
            added_by="enrichment.technology",
        )
        notes.append(f"Defensibility markers: {summary}.")

    if weak:
        notes.extend(f"⚠️ {w}" for w in weak)

    if not strong and not weak:
        notes.append("No defensibility markers found in available text.")

    return notes


def scalability_signal(startup: Startup) -> tuple[int | None, str]:
    """Rate scalability 0-5 from business-model language. None when no text."""
    text = " ".join(p for p in [startup.business_model, startup.product_summary,
                                startup.technology] if p)
    if not text.strip():
        return None, "No business-model or product text available."

    positive = len(set(m.group(0).lower() for m in SCALABILITY_POSITIVE.finditer(text)))
    negative = len(set(m.group(0).lower() for m in SCALABILITY_NEGATIVE.finditer(text)))

    if negative and not positive:
        return 1, f"Service-delivery language only ({negative} marker(s)) — margin and scale likely limited."
    if negative and positive:
        return 3, "Mixed model: product language alongside service-delivery language."
    if positive >= 3:
        return 5, f"Clear software/product economics ({positive} markers)."
    if positive == 2:
        return 4, "Product economics indicated."
    if positive == 1:
        return 3, "Some product language, but the model is not clearly described."
    return 2, "Business model not clearly described in available text."


def moat_strength(startup: Startup) -> tuple[int | None, str]:
    """Rate technical differentiation 0-5 from the markers present."""
    text = " ".join(p for p in [startup.technology, startup.technical_moat,
                                startup.product_summary] if p)
    if not text.strip():
        return None, "No technology or moat description available."

    strong = [d for p, d in MOAT_MARKERS.items() if re.search(p, text, re.IGNORECASE)]
    weak = [d for p, d in WEAK_MARKERS.items() if re.search(p, text, re.IGNORECASE)]

    if weak and not strong:
        return 1, f"Weak-differentiation signals only: {'; '.join(weak)}."
    if len(strong) >= 3:
        return 5, f"Several independent defensibility markers: {'; '.join(strong[:3])}."
    if len(strong) == 2:
        return 4, f"Two defensibility markers: {'; '.join(strong)}."
    if len(strong) == 1:
        return 3, f"One defensibility marker: {strong[0]}."
    return 2, "Technology described but no concrete defensibility marker found."
