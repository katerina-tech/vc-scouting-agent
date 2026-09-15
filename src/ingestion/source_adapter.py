"""The ``SourceAdapter`` contract that every discovery source implements.

Adding a new source (Dealroom, Crunchbase, an accelerator cohort page, a VC
portfolio page, Product Hunt, a web-search backend) means writing one subclass
and registering it. Nothing else in the application changes.

Two rules every adapter must honour:

1. **Never fabricate access.** An adapter for a paid API that has no key must
   report itself unavailable and explain how to configure it — it must not
   invent results.
2. **Never scrape in violation of terms of service.** Adapters either use an
   official API, a user-supplied file, or a company's own public homepage.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..models.enums import Dataset, SourceType
from ..models.evidence import Evidence
from ..models.startup import Startup


@dataclass
class IngestionResult:
    """What every adapter returns: companies, their evidence, and any problems."""

    startups: list[Startup] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rows_seen: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "IngestionResult") -> "IngestionResult":
        self.startups.extend(other.startups)
        self.evidence.extend(other.evidence)
        self.warnings.extend(other.warnings)
        self.errors.extend(other.errors)
        self.rows_seen += other.rows_seen
        return self


class SourceAdapter(ABC):
    """Base class for every discovery source."""

    #: Short machine name, stored on each startup as ``source_adapter``.
    name: str = "abstract"
    #: Human label for the UI.
    label: str = "Abstract source"
    #: What kind of source this is, for the evidence tier hierarchy.
    source_type: SourceType = SourceType.OTHER
    #: Set False for adapters that require a licence the user may not hold.
    requires_api_key: bool = False

    @abstractmethod
    def fetch(self, **kwargs: Any) -> IngestionResult:
        """Return companies from this source."""

    def is_available(self) -> bool:
        """Whether this adapter can actually run right now."""
        return True

    def unavailable_reason(self) -> str:
        return ""

    def describe(self) -> str:
        return self.label


class UnavailableSourceAdapter(SourceAdapter):
    """A documented stub for a source that needs credentials we do not have.

    It deliberately returns an *error*, never fake rows. The message tells the
    operator exactly what to configure.
    """

    def __init__(self, name: str, label: str, env_var: str, docs_url: str, notes: str = "") -> None:
        self.name = name
        self.label = label
        self.env_var = env_var
        self.docs_url = docs_url
        self.notes = notes
        self.requires_api_key = True
        self.source_type = SourceType.STARTUP_DATABASE

    def is_available(self) -> bool:
        from ..config import get_source_api_key

        return bool(get_source_api_key(self.name))

    def unavailable_reason(self) -> str:
        return (
            f"{self.label} requires a licensed API key. Set `{self.env_var}` in your .env "
            f"and implement `fetch()` against {self.docs_url}. "
            f"{self.notes}".strip()
        )

    def fetch(self, **kwargs: Any) -> IngestionResult:
        return IngestionResult(errors=[self.unavailable_reason()])


#: Stubs for the integrations most likely to be added next. Each is honest
#: about needing a licence; none of them ever returns invented data.
PLANNED_ADAPTERS: list[UnavailableSourceAdapter] = [
    UnavailableSourceAdapter(
        name="dealroom",
        label="Dealroom",
        env_var="DEALROOM_API_KEY",
        docs_url="https://dealroom.co/solutions/api",
        notes="Best single source for verified European early-stage funding rounds.",
    ),
    UnavailableSourceAdapter(
        name="crunchbase",
        label="Crunchbase",
        env_var="CRUNCHBASE_API_KEY",
        docs_url="https://data.crunchbase.com/docs",
        notes="Broad coverage; weaker on European pre-seed.",
    ),
    UnavailableSourceAdapter(
        name="accelerator_cohorts",
        label="Accelerator cohort lists",
        env_var="ACCELERATOR_COHORTS_API_KEY",
        docs_url="(per-accelerator; many publish machine-readable cohort pages)",
        notes="Highest-signal source for pre-seed; usually needs a per-accelerator parser.",
    ),
    UnavailableSourceAdapter(
        name="vc_portfolios",
        label="VC portfolio pages",
        env_var="VC_PORTFOLIOS_API_KEY",
        docs_url="(per-fund; check each site's terms before automated access)",
        notes="Useful for co-investor mapping. Respect each site's robots.txt and ToS.",
    ),
    UnavailableSourceAdapter(
        name="producthunt",
        label="Product Hunt",
        env_var="PRODUCTHUNT_API_KEY",
        docs_url="https://api.producthunt.com/v2/docs",
        notes="Good for launch-stage traction signals, weak on funding data.",
    ),
    UnavailableSourceAdapter(
        name="web_search",
        label="Public web search",
        env_var="WEB_SEARCH_API_KEY",
        docs_url="(Brave / Tavily / Bing Web Search API)",
        notes="Recommended first live-discovery integration — see README.",
    ),
]


def adapter_registry() -> dict[str, SourceAdapter]:
    """All adapters the app knows about, live ones plus documented stubs."""
    from .csv_loader import CSVSourceAdapter
    from .manual_loader import ManualEntryAdapter, URLSourceAdapter

    registry: dict[str, SourceAdapter] = {
        "csv": CSVSourceAdapter(),
        "manual": ManualEntryAdapter(),
        "url": URLSourceAdapter(),
    }
    for stub in PLANNED_ADAPTERS:
        registry[stub.name] = stub
    return registry


def default_dataset_for(is_demo: bool) -> Dataset:
    return Dataset.DEMO if is_demo else Dataset.REAL
