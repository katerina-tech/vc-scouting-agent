"""The investment thesis — fully configurable from the Streamlit UI.

The default below is the fund's stated thesis. Everything about it (geography,
stages, sectors, funding ceiling, founding-year floor, free-text description)
can be edited at runtime, and the thesis in force is stored alongside every
scoring run so results stay reproducible.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import Stage

DEFAULT_THEMES: list[str] = ["Climate", "Health", "Economic Empowerment"]

DEFAULT_THESIS_TEXT = (
    "We back pre-seed and seed European companies building highly scalable, "
    "technology-enabled businesses with a potentially defensible advantage, "
    "addressing large markets, and producing measurable real-world impact in "
    "climate, health, or economic empowerment."
)

DEFAULT_CHARACTERISTICS: list[str] = [
    "highly scalable",
    "technology-enabled",
    "potentially defensible",
    "large market",
    "measurable real-world impact",
]

#: Geographies. Europe is the default scope; the set is editable in the UI.
EUROPE_COUNTRIES: set[str] = {
    "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herzegovina",
    "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland",
    "France", "Germany", "Greece", "Hungary", "Iceland", "Ireland", "Italy",
    "Kosovo", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Malta",
    "Moldova", "Monaco", "Montenegro", "Netherlands", "North Macedonia", "Norway",
    "Poland", "Portugal", "Romania", "San Marino", "Serbia", "Slovakia", "Slovenia",
    "Spain", "Sweden", "Switzerland", "Ukraine", "United Kingdom",
}


class InvestmentThesis(BaseModel):
    """A thesis is a filter plus a set of preferences, not a scoring black box."""

    name: str = "Default thesis"
    geographies: set[str] = Field(default_factory=lambda: set(EUROPE_COUNTRIES))
    geography_label: str = "Europe"
    stages: set[Stage] = Field(default_factory=lambda: {Stage.PRE_SEED, Stage.SEED})
    themes: list[str] = Field(default_factory=lambda: list(DEFAULT_THEMES))
    max_total_funding_eur: float = 3_000_000.0
    min_founded_year: int | None = 2018
    require_active: bool = True
    characteristics: list[str] = Field(default_factory=lambda: list(DEFAULT_CHARACTERISTICS))
    thesis_text: str = DEFAULT_THESIS_TEXT

    model_config = {"use_enum_values": False}

    def matches_geography(self, country: str | None) -> bool | None:
        """True / False / None when the country is unknown."""
        if not country:
            return None
        return country in self.geographies

    def matches_stage(self, stage: Stage) -> bool | None:
        if stage == Stage.UNKNOWN:
            return None
        return stage in self.stages

    def matches_theme(self, themes: list[str]) -> bool | None:
        if not themes:
            return None
        wanted = {t.strip().lower() for t in self.themes}
        return any(t.strip().lower() in wanted for t in themes)

    def summary(self) -> str:
        stages = ", ".join(sorted(s.label for s in self.stages)) or "any stage"
        themes = ", ".join(self.themes) or "any theme"
        year = f", founded {self.min_founded_year} or later" if self.min_founded_year else ""
        return (
            f"{self.geography_label} · {stages} · ≤ €{self.max_total_funding_eur:,.0f} "
            f"total funding{year} · {themes}"
        )

    def to_storable(self) -> dict:
        data = self.model_dump(mode="json")
        data["geographies"] = sorted(self.geographies)
        data["stages"] = sorted(s.value for s in self.stages)
        return data

    @classmethod
    def from_storable(cls, data: dict) -> "InvestmentThesis":
        payload = dict(data)
        payload["geographies"] = set(payload.get("geographies") or EUROPE_COUNTRIES)
        payload["stages"] = {Stage(s) for s in (payload.get("stages") or ["PRE_SEED", "SEED"])}
        return cls(**payload)
