"""Central configuration.

Every tunable value is read from the environment (optionally via a local
``.env`` file). No secret is ever hard-coded, and the application is designed
to run with an empty environment — in that case the LLM layer is disabled and
all analysis falls back to deterministic logic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXPORT_DIR = DATA_DIR / "exports"

APP_NAME = "VC Startup Scouting Agent"
APP_VERSION = "0.1.0"
APP_TAGLINE = "Evidence-first discovery and research for early-stage European startups"

#: Shown on every page. The tool structures research; it does not predict outcomes.
APP_DISCLAIMER = (
    "This tool structures startup discovery and investment research. "
    "It does **not** predict investment success and never makes an investment "
    "decision. Every score is explainable, every fact is traceable to a source, "
    "and the final judgement stays with the investor."
)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name) or default)
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name) or default))
    except (TypeError, ValueError):
        return default


def get_db_path() -> Path:
    raw = os.getenv("VC_DB_PATH")
    if raw and raw.strip():
        return Path(raw.strip()).expanduser()
    return DATA_DIR / "vc_scouting.db"


@dataclass(frozen=True)
class LLMSettings:
    """Everything the LLM adapter needs. ``enabled`` is only True when a key exists."""

    enabled: bool
    api_key: str | None
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout: int

    @property
    def is_usable(self) -> bool:
        return bool(self.enabled and self.api_key and self.base_url and self.model)

    def describe(self) -> str:
        if not self.enabled:
            return "Disabled (LLM_ENABLED is false) — deterministic analysis only."
        if not self.api_key:
            return "Enabled but no LLM_API_KEY found — falling back to deterministic analysis."
        return f"{self.model} via {self.base_url}"


def get_llm_settings() -> LLMSettings:
    return LLMSettings(
        enabled=_bool_env("LLM_ENABLED", False),
        api_key=(os.getenv("LLM_API_KEY") or "").strip() or None,
        base_url=(os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/"),
        model=(os.getenv("LLM_MODEL") or "gpt-4o-mini").strip(),
        temperature=_float_env("LLM_TEMPERATURE", 0.2),
        max_tokens=_int_env("LLM_MAX_TOKENS", 2000),
        timeout=_int_env("LLM_TIMEOUT", 60),
    )


@dataclass(frozen=True)
class EnrichmentSettings:
    """Controls the optional, polite fetch of a company's own homepage."""

    fetch_enabled: bool
    user_agent: str
    timeout: int


def get_enrichment_settings() -> EnrichmentSettings:
    return EnrichmentSettings(
        fetch_enabled=_bool_env("ENRICHMENT_FETCH_ENABLED", False),
        user_agent=(
            os.getenv("ENRICHMENT_USER_AGENT")
            or "vc-scouting-agent/0.1 (+research use)"
        ).strip(),
        timeout=_int_env("ENRICHMENT_TIMEOUT", 15),
    )


def get_source_api_key(source: str) -> str | None:
    """Key for a paid data source adapter, or None when not configured."""
    value = os.getenv(f"{source.upper()}_API_KEY")
    return value.strip() if value and value.strip() else None
