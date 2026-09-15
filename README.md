# VC Startup Scouting Agent

**An evidence-first tool for discovering, researching, ranking and shortlisting real early-stage European startups.**

> This application **does not predict investment success.** It structures startup discovery and investment research so that an investor can defend every claim, see every source, and spend their attention on two or three companies worth a real conversation.

---

## Contents

- [The problem](#the-problem)
- [What it does](#what-it-does)
- [Product principles](#product-principles)
- [Architecture](#architecture)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Running it](#running-it)
- [The data model](#the-data-model)
- [The scoring model](#the-scoring-model)
- [The eligibility engine](#the-eligibility-engine)
- [Evidence, confidence and source quality](#evidence-confidence-and-source-quality)
- [The LLM's role](#the-llms-role)
- [Human-in-the-loop](#human-in-the-loop)
- [Demo data](#demo-data)
- [Getting real companies](#getting-real-companies)
- [The import wizard](#the-import-wizard)
- [Source adapters — and how to add one](#source-adapters--and-how-to-add-one)
- [Testing](#testing)
- [Limitations](#limitations)
- [Ethical considerations](#ethical-considerations)
- [Recommended next integration](#recommended-next-integration)

---

## The problem

An investor screening early-stage European companies faces three failures at once:

1. **Discovery is fragmented.** Pre-seed companies appear in accelerator cohorts, niche newsletters, and a founder's LinkedIn post before they appear in any database.
2. **Data is unreliable.** Funding figures disagree between sources, "customers" on a homepage are often pilots, and a "€40bn market" is usually a company's own slide.
3. **The tempting fix makes it worse.** A model that scores startups on success probability produces a confident number with no traceable reasoning — exactly the thing that cannot be defended in an investment committee.

This tool takes the opposite approach. It is a **research instrument**, not an oracle. Its output is a short, defensible shortlist where every claim carries a source and every score carries its reasoning.

## What it does

```
File import (any columns) / sourcing list / manual entry / company URL
        ↓
normalization  (names · URLs · countries · currency→EUR · dates · stages · sectors)
        ↓
deduplication  (domain first, then normalized name; evidence-preserving merge)
        ↓
enrichment     (signals extracted from text and the company's own homepage — never invented)
        ↓
ELIGIBILITY    (deterministic hard filters → ELIGIBLE / NEEDS_REVIEW / INELIGIBLE, with reasons)
        ↓
SCORING        (transparent 100-point framework; unrated where evidence is missing)
        ↓
RED FLAGS      (shown beside the score, never subtracted from it)
        ↓
RANKING → human review → FINAL SHORTLIST → investment memo → Loom script
```

Six Streamlit views: **Discovery · Candidates · Company Research · Ranking · Investment Memo · Final Shortlist.**

### The funnel

Ranking and Final Shortlist each open with a funnel chart that shows the narrowing explicitly — sourced → passed the hard filters → scored and rankable → top 5 → final shortlist — followed by a plain-language line ("19 companies sourced, 3 taken forward — an 84% reduction") and an expander naming what each stage removed and why. The counts come from the live workspace, not from a fixed picture, so if the thesis changes the funnel changes with it. It exists because "here are three companies" is not an answer on its own; "here are three companies out of nineteen, and here is what happened to the other sixteen" is.

## Product principles

These are not aspirations; each one is enforced in code and covered by a test.

| # | Principle | Where it lives |
|---|---|---|
| 1 | Evidence first | `Evidence` model; nothing important renders without `field_block()` |
| 2 | Never fabricate startup information | `llm/prompts.py`; `merge_llm_ratings()` rejects invented ratings |
| 3 | Never infer funding eligibility without evidence | `filters/eligibility.py::_funding_check` |
| 4 | Preserve source URLs | `source_urls`, `Evidence.source_url`, `refresh_startup_confidence()` |
| 5 | Make scoring explainable | `CriterionScore` carries rating, weight, reasoning, evidence IDs, confidence |
| 6 | Separate facts from inference | `VerificationStatus` · `ClaimType` (FACT/INFERENCE/OPINION/UNKNOWN) |
| 7 | Allow human overrides | `HumanOverride`, `overrides` table, override UI on three pages |
| 8 | Optimise for a high-quality shortlist | Ranking is capped at the eligible set; the shortlist view warns above 5 |
| 9 | Real current companies are the objective | Demo data is isolated in its own dataset and labelled everywhere |
| 10 | Investment judgement stays human | `Recommendation` has no `INVEST` member — by construction |

## Architecture

```
app.py                          Streamlit entry point (thin — routing only)
src/
  config.py                     env-driven settings; no hard-coded secrets
  pipeline.py                   orchestration: ingest → assess → persist
  models/
    enums.py                    controlled vocabularies (status, tier, stage, …)
    startup.py                  the Startup domain model + HumanOverride
    evidence.py                 Evidence + FieldAssessment
    scoring.py                  CriterionScore, ScoreBreakdown, RedFlag, EligibilityResult
    thesis.py                   InvestmentThesis (configurable at runtime)
  ingestion/
    source_adapter.py           SourceAdapter ABC + honest stubs for paid sources
    csv_loader.py               flexible CSV import, one Evidence per field
    manual_loader.py            manual form + URL entry
  normalization/
    company_normalizer.py       names, URLs, countries, money→EUR, dates, stages, themes
    deduplication.py            domain/name matching + evidence-preserving merge
  filters/
    eligibility.py              deterministic hard filters with per-check reasons
  enrichment/
    company_enrichment.py       robots-respecting homepage read (opt-in)
    funding.py founders.py traction.py market.py technology.py
  scoring/
    score_config.py             the 100 points, weights and rating guides
    score_engine.py             per-criterion raters, LLM merge, overrides, ranking
  llm/
    client.py                   OpenAI-compatible adapter + Null fallback + usage/cost
    prompts.py                  the anti-fabrication prompts and the evidence dossier
    investment_analyst.py       validated analyst facade with deterministic fallbacks
  research/
    evidence_manager.py         the single source of truth for "what do we know?"
    confidence.py               source-quality → confidence rules
    red_flags.py                red-flag detection and diligence questions
  reports/
    investment_memo.py          memo assembly + PASS/WATCH/INVESTIGATE logic
    loom_script.py              45–60 second spoken pitch
  storage/
    database.py                 SQLite schema
    repository.py               the only code that touches SQL
  ui/
    theme.py                    the design system: palette, CSS, chart layout
    state.py components.py      session state and the evidence viewer
    import_wizard.py            file import with explicit column mapping
    sources.py                  catalogue of open data sources
    discovery.py candidates.py research.py ranking.py memo.py shortlist.py
.streamlit/config.toml          Streamlit's own theme tokens, matched to theme.py
tests/                          185 tests, no API key or network required
data/real_startups_2026.csv     19 real companies, each verified against its source
data/sample_startups.csv        4 clearly-labelled fictional demo companies
```

Two deviations from the brief's sketch, both deliberate: `src/ui/` exists so `app.py` stays thin (the brief asks not to put everything in one giant file), and `src/research/red_flags.py` and `src/models/thesis.py` were split out rather than buried in adjacent modules.

**Why SQLite and not DuckDB:** the workload is transactional reads and writes of a few thousand rows from a Streamlit session, not analytical scanning. SQLite is in the standard library, needs no service, and stores one portable file.

## Setup

```bash
git clone <your-repo-url>
cd vc-scouting-agent

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
cp .env.example .env               # optional — the app runs fine without editing it
```

Python 3.11 or newer.

## Environment variables

Everything is optional. **With an empty `.env` the application runs in fully deterministic mode** — scoring, eligibility, memos and Loom scripts all work; only the LLM-written prose is unavailable.

| Variable | Default | What it does |
|---|---|---|
| `LLM_ENABLED` | `false` | Master switch for the analyst model |
| `LLM_API_KEY` | — | Key for any OpenAI-compatible endpoint |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI, OpenRouter, Together, local vLLM… |
| `LLM_MODEL` | `gpt-4o-mini` | Model id |
| `LLM_TEMPERATURE` | `0.2` | Low by design — this is analysis, not creative writing |
| `LLM_MAX_TOKENS` | `2000` | Per-call ceiling |
| `LLM_TIMEOUT` | `60` | Seconds |
| `VC_DB_PATH` | `./data/vc_scouting.db` | Where SQLite lives |
| `ENRICHMENT_FETCH_ENABLED` | `false` | Allow reading a company's **own** homepage |
| `ENRICHMENT_USER_AGENT` | `vc-scouting-agent/0.1` | Sent when fetching; put a contact address in it |
| `ENRICHMENT_TIMEOUT` | `15` | Seconds |
| `DEALROOM_API_KEY` | — | Unlocks the Dealroom adapter stub |
| `CRUNCHBASE_API_KEY` | — | Unlocks the Crunchbase adapter stub |

No secret is ever hard-coded, logged, or written to the database.

## Running it

```bash
streamlit run app.py
```

Then, in the app:

1. **Discovery** → keep the default thesis (Europe · Pre-seed/Seed · ≤ €3M · Climate, Health, Economic Empowerment) or edit it.
2. Click **🧪 Load the 8 demo companies** to see the whole flow immediately.
3. **Candidates** → sort, filter, pick one.
4. **Company Research** → read the evidence, attach a source, correct a field, approve a *Needs review* company.
5. **Ranking** → see the score broken into its eight criteria, override any of them with a reason, add the best to the shortlist.
6. **Investment Memo** → generate the memo and the Loom script.
7. **Final Shortlist** → compare 2–5 companies side by side and export to CSV.

## The data model

`Startup` carries every field the brief specifies, plus the machinery that makes those fields trustworthy:

- **Raw next to normalized.** `total_funding_raw = "€1.8M"` sits beside `total_funding_eur = 1800000.0`, with `fx_note` recording the conversion rate used.
- **`funding_status` is separate from the funding value.** A number without a credible source is `UNVERIFIED`; no number at all is `MISSING`. Neither is ever treated as "under the ceiling".
- **`dataset`** is `DEMO` or `REAL`. The two pools are queried separately, deduplicated separately, and never merged.
- **`human_overrides`** records every investor intervention with old value, new value, reason, author and timestamp.

`Evidence` is one factual claim about one field, with `source_url`, `source_title`, `source_type`, derived `source_tier`, `retrieved_at`, `confidence`, `verification_status` and `evidence_note`. An LLM inference is stored as evidence too — with `source_type = LLM_INFERENCE`, and the model forbids it from ever being labelled `VERIFIED` on its own.

Every field is classified as one of:

| Status | Meaning |
|---|---|
| **VERIFIED** | Backed by a credible external source, or personally confirmed by the investor |
| **INFERRED** | Derived by the system or the model from other text |
| **UNVERIFIED** | A value exists, but nothing backs it up |
| **MISSING** | No value at all |

## The scoring model

A transparent 100-point framework. The weights live in exactly one place (`src/scoring/score_config.py`) and a test asserts they still total 100.

| Criterion | Weight | The question it asks |
|---|---:|---|
| Thesis Fit | 20 | How squarely does this sit inside the fund's stated thesis? |
| Problem Magnitude / Market Potential | 20 | How large and how painful is the problem? |
| Founder-Market Fit | 15 | Why is *this* team uniquely able to solve *this* problem? |
| Product / Technical Differentiation | 15 | What stops a well-funded competitor copying this in 12 months? |
| Traction Signals | 10 | What evidence exists that someone actually wants this? |
| Why Now / Market Timing | 10 | What changed recently that makes this possible or necessary now? |
| Scalability | 5 | Can revenue grow far faster than headcount? |
| Capital Efficiency | 5 | How much was achieved per euro raised? |
| **Total** | **100** | |

Each criterion is rated **0–5** and weighted:

```
weighted_score = raw_rating / 5 × weight
```

Every `CriterionScore` carries `criterion`, `raw_rating`, `weight`, `weighted_score`, `reasoning`, `evidence_ids` and `confidence`.

**The rule that matters most:** *if there is no evidence for a criterion, the rating is `None`.* Not 0, not the average, not "3 because most things are 3". The criterion's weight is then excluded from `assessable_weight`, so the UI can say **"62 out of a possible 85 assessed"** rather than pretending the missing 15 points were a bad score. `evidence_coverage` makes this visible on every company.

Ties break towards better-evidenced companies: a well-sourced 70 outranks a speculative 70.

**Recommendations** are `PASS`, `WATCH` or `INVESTIGATE`. There is deliberately **no `INVEST`** — the enum has no such member, and a test asserts it. A company cannot reach `INVESTIGATE` if evidence coverage is below 65%, if evidence confidence is below 0.45, if any high-severity red flag is open, or if three or more medium-severity concerns stack up — no matter how high the arithmetic score.

## The eligibility engine

Deterministic hard filters run **before** any scoring. Default thesis:

```
Europe  AND  active  AND  pre-seed or seed  AND  total funding < €3,000,000  AND  matches ≥1 theme
```

Three outcomes, always with reasons:

- **ELIGIBLE** — every check passed on evidence.
- **INELIGIBLE** — at least one check failed on evidence.
- **NEEDS_REVIEW** — nothing failed, but something could not be determined.

> ### The unknown-funding rule
>
> **If total funding cannot be verified, the company is not eligible.** It becomes `NEEDS_REVIEW` with the reason *"Funding amount could not be verified — NOT assumed to be below the ceiling."*
>
> This also applies to a number that exists but has no credible source. `€1.2M (UNVERIFIED)` does not pass the €3M ceiling test; it goes to review. Nine tests in `tests/test_eligibility.py` cover this rule alone, because it is the single easiest place for a screening tool to quietly lie to its user.

`NEEDS_REVIEW` companies are excluded from ranking until a human ticks *"I have reviewed this company and approve it for ranking"*.

## Evidence, confidence and source quality

**Source hierarchy:**

| Tier | Sources | Base confidence |
|---|---|---:|
| **Tier 1** | Official company website · funding announcement · investor announcement · regulatory records | 0.92 |
| **Tier 2** | Reputable business media · established startup databases | 0.75 |
| **Tier 3** | LinkedIn · startup directories · accelerator pages | 0.50 |
| **Tier 4** | Blogs · unverified aggregators | 0.30 |
| **None** | User input · model inference | 0.15 |

**Confidence levels:**

| Level | When |
|---|---|
| 🟢 **HIGH** | Two or more independent Tier-1/2 sources agree, or a human marked it verified |
| 🟡 **MEDIUM** | One credible source, or several agreeing weaker sources |
| 🟠 **LOW** | Indirect evidence or model inference |
| 🔴 **UNVERIFIED** | No reliable evidence |

Disagreement never raises confidence. Two sources that differ by more than 10% on a number push the field to `UNVERIFIED`, cap its confidence at 0.4, and raise a `conflicting_funding_data` red flag.

**Red flags** are displayed *beside* the score, never subtracted from it. A crowded market is a reason to ask a question, not a reason for a tool to silently demote a company. Detected flags include: funding unverifiable · above the ceiling · conflicting funding data · unclear business model · consulting presented as SaaS · crowded market · weak technical moat · no visible founder-market fit · no traction evidence · customer concentration · regulatory dependency · inactive website · already acquired · stale round · unknown stage. Each can be dismissed by the investor, and the dismissal is recorded.

## The LLM's role

The model is an **investment analyst assistant, not a source of truth.** It is used for: summarising evidence, thesis-fit reasoning, identifying potential moats, market questions, why-now reasoning, additional red flags, founder diligence questions, memo drafts and Loom drafts.

It is forbidden from inventing funding amounts, customers, revenues, investors, founder experience, market numbers or partnerships. When the dossier is silent, it must write exactly **"Insufficient public evidence."** Every substantive statement is labelled `FACT`, `INFERENCE`, `OPINION` or `UNKNOWN`.

Four mechanisms enforce this rather than merely requesting it:

1. **The dossier is the only input.** `build_dossier()` constructs an explicit evidence block with each field's verification status and confidence, ending with *"anything not above is UNKNOWN"*.
2. **Output is validated by Pydantic.** Anything that does not match the schema is discarded and the deterministic path runs instead.
3. **The LLM cannot create a score from nothing.** `merge_llm_ratings()` refuses any rating for a criterion the deterministic engine left unrated, and annotates the rejection. Invented criteria are dropped silently.
4. **Every feature has a deterministic implementation.** The fallback is not an error path — it is the default mode of the product.

Token usage and an approximate cost estimate are shown in the sidebar.

## Human-in-the-loop

The investor can: edit any field (stored as an override with a reason), approve or reject eligibility, override any score criterion, add notes, mark evidence verified, add a source they found themselves, dismiss a red flag, and move companies on and off the shortlist. Every override is persisted in the `overrides` table and visible on the company's **Audit trail** tab.

## Demo data

`data/sample_startups.csv` contains **4 fictional companies**, every one prefixed `DEMO` and marked `FICTIONAL DEMO COMPANY` in its notes. The set is deliberately small — real companies are the point of the product, and the demo set exists only to prove the pipeline runs end to end. The four rows are chosen to hit every eligibility outcome: one clean `ELIGIBLE`, one with unknown funding that becomes `NEEDS_REVIEW`, one above the funding ceiling that becomes `INELIGIBLE`, and one eligible-but-weak company that exposes a thin moat in the score. They live in a separate `DEMO` dataset that is queried, deduplicated and displayed apart from real companies — a test asserts demo data never reaches the real dataset.

They are constructed to exercise every path: a strong eligible company; unknown funding (`NEEDS_REVIEW`); funding with no source URL (`NEEDS_REVIEW`); €12M raised (`INELIGIBLE`); a consulting-business-as-SaaS with a thin GPT-wrapper moat and six competitors; and several genuinely plausible candidates.

## Getting real companies

### The bundled verified pipeline

`data/real_startups_2026.csv` contains **19 real European companies** that announced a pre-seed or seed round under €3M. Each one was found through published funding coverage and **checked against the original article before entry** on 15 September 2026. Every row carries a `funding_source_url`, so the funding figures import as VERIFIED and the companies can legitimately clear the thesis ceiling.

Sources: EU-Startups, Tech.eu, ArcticStartup, Femtech Insider, Pulse 2.0, TechFundingNews.

Load it from Discovery with **Load 19 verified real companies**. The Candidates and Final Shortlist pages both carry a **Data provenance** panel that states, computed from the evidence records rather than written by hand, how many companies carry a sourced funding figure and which domains they came from.

Two caveats that travel with the data and are recorded in each row's notes:

- **Metal Morph** and **TaskHer** publish their totals in sterling. The euro figure is converted by the application at the documented static rate; the raw sterling figure is preserved alongside it.
- **Muun Health**'s total includes a €700k Enterprise Estonia grant, which is non-dilutive rather than a venture round.

### Open sources to extend it

The application never scrapes a third-party database and never invents a company, so beyond the bundled set it needs to be fed. These are the open sources an investor can legitimately use today, all free unless marked:

| Source | What it gives you | Tier |
|---|---|---|
| **[EPO Deep Tech Finder](https://www.epo.org/en/searching-for-patents/business/deep-tech-finder)** | European university spin-outs and investment-ready startups holding published patent applications: name, country, technology field, patent families | Tier 1 |
| **[EIC Accelerator](https://eic.ec.europa.eu/eic-funding-opportunities/eic-accelerator_en)** | The European Commission's own list of companies selected in each cut-off round, with country and amount awarded | Tier 1 |
| **[CORDIS / data.europa.eu](https://cordis.europa.eu/about/services)** | Bulk datasets of every organisation in Horizon Europe and H2020, with EU contributions, in XML/CSV/XLS | Tier 1 |
| **[OpenCorporates](https://opencorporates.com/)** | Official registry records: incorporation date, status, registered address | Tier 1 |
| **[ESNA Data Platform](https://data.esnalliance.eu)** | Startup counts and investment flows across EU member states | Tier 2 |
| **[Dealroom](https://dealroom.co/) / Crunchbase** | Funding rounds, investors, stages — if your fund holds a licence | Tier 2 |

The **Data sources** tab inside Discovery carries this catalogue with step-by-step download instructions for each.

Two honest caveats the app states in the interface as well as here. The EPO index only covers companies with patent applications, so it under-represents software; and an EIC grant or a Horizon contribution is **not** a VC round, so importing one as "funding" is a judgement call about whether the thesis ceiling is meant to include non-dilutive money.

### When you have no file at all

The **Sourcing list** tab takes a pasted list — one company per line, as a URL, a name, or `Name, https://url` — and creates one skeleton record each. It is the fastest honest route from "I found twenty interesting companies this morning" to a structured research queue. Every record arrives empty and UNVERIFIED, ready to be researched field by field.

## The import wizard

Every real source spells its columns differently: EPO says *Applicant name*, the EIC says *Beneficiary*, Dealroom says *Name*. Guessing is fragile and fails silently, so the wizard does not guess.

1. **Choose a file.** CSV, TSV or Excel. Separator and encoding are sniffed, so a semicolon-separated Latin-1 European export works untouched.
2. **Declare what kind of source it is.** This, not the file format, sets the evidence tier — and therefore how confident the application is permitted to be about everything in the file. An official register imports at Tier 1; a directory export at Tier 3. A test asserts the two produce different confidence for the same row.
3. **Map the columns.** Recognisable names are pre-selected; everything else stays blank. An unmapped column is ignored, never interpreted.
4. **Preview and import.** If no funding-source-URL column is mapped, the wizard says so up front: the funding figures will import UNVERIFIED and the companies will land in *Needs review*, because a number without a source cannot clear a ceiling.

## Source adapters — and how to add one

Four inputs work today: **file import with column mapping**, **a pasted sourcing list**, **manual entry** and **company URL**.

Adapters for Dealroom, Crunchbase, accelerator cohorts, VC portfolio pages, Product Hunt and public web search exist as **honest stubs**. Without a configured key they report themselves unavailable and name the exact environment variable to set. They never return invented rows — a test asserts it.

**To add a new source:**

```python
# src/ingestion/my_source.py
from .source_adapter import IngestionResult, SourceAdapter
from ..models.enums import SourceType

class MySourceAdapter(SourceAdapter):
    name = "my_source"
    label = "My Source"
    source_type = SourceType.STARTUP_DATABASE   # sets the evidence tier

    def is_available(self) -> bool:
        from ..config import get_source_api_key
        return bool(get_source_api_key("my_source"))

    def fetch(self, **kwargs) -> IngestionResult:
        result = IngestionResult()
        if not self.is_available():
            result.errors.append("Set MY_SOURCE_API_KEY in your .env.")
            return result
        for record in call_the_api(**kwargs):
            startup, evidence, warnings = row_to_startup(record, adapter_name=self.name)
            ...
        return result
```

Then register it in `adapter_registry()`. Nothing else changes: normalization, deduplication, eligibility, scoring and the UI all work off the `IngestionResult` contract.

Two rules every adapter must honour: **never fabricate access** (no key means unavailable, not fake rows) and **never scrape in violation of terms of service** (use an official API, a user-supplied file, or a company's own public homepage — and respect `robots.txt`).

## Testing

```bash
pytest tests/ -q          # 185 tests, ~1 second, no API key and no network
```

Coverage maps to the brief's checklist:

| Requirement | Tests |
|---|---|
| Funding threshold | `test_funding_below_ceiling_passes_when_verified`, `…at_the_ceiling_fails`, `…above_ceiling_fails` |
| Unknown funding | `test_unknown_funding_is_never_assumed_to_be_under_the_ceiling`, `test_reported_but_unverified_funding_needs_review` |
| Currency normalization | 10 parametrised spellings, FX conversion, unknown-currency refusal |
| Stage normalization | 11 aliases + "unrecognised means UNKNOWN, not a guess" |
| European geography | Europe / non-Europe / unknown-is-not-false |
| Score calculation | Weighted arithmetic, a perfect 100 ceiling, thesis-fit behaviour |
| Weights summing to 100 | `test_weights_sum_to_exactly_100` + `validate_weights()` at import time |
| Missing evidence | Unrated not zero-rated, excluded from assessable weight, LLM cannot fill the gap |
| Duplicate detection | Domain match, name match, demo/real isolation, merge semantics |
| Import and mapping | Semicolon/Latin-1/Excel reading, explicit mapping, refusal without a company-name column, tier set by declared source type, unmapped columns never interpreted |
| Funding figures | `test_plain_integers_are_not_truncated` — a regression guard after a parser bug silently read `1400000` as `140`, which would have let a company clear a €3M ceiling it had no business clearing |
| Confidence assignment | Tier hierarchy, multi-source agreement, conflict handling, human verification |

Plus end-to-end ingestion, SQLite round-trips, adapter honesty, memo completeness without an LLM, the no-`INVEST` guarantee, and Loom scripts landing inside the 45–60 second window.

## Limitations

- **Live discovery is not implemented.** Version 1 discovers nothing on its own; it structures what you feed it. The adapters are the path forward, not a substitute for having one configured.
- **FX rates are static**, dated `2024-06-01` and documented in `company_normalizer.py`. Reproducibility was chosen over freshness for a research tool; every converted figure records the rate used. Revisit before relying on a borderline conversion near the €3M ceiling.
- **Theme mapping is keyword-based.** A company whose language does not match the taxonomy is marked "no theme found" and sent to review rather than being forced into a theme — conservative, but it will miss unusual phrasing.
- **Enrichment reads marketing copy.** Homepage text is a company's own claim about itself. Everything derived from it is `INFERRED` or `UNVERIFIED` by construction, never fact.
- **Traction extraction detects claims, not verified metrics.** "Trusted by 200 clinics" becomes a recorded claim with a source, not a number the score treats as true.
- **The scoring framework is one fund's opinion.** The weights are defensible, not objective. They are in one file so they can be argued with and changed.
- **No multi-user support.** One SQLite file, one workspace, no authentication.
- **Column mapping is manual by design.** The wizard pre-selects only names it recognises. That is slower than an auto-importer and deliberately so: a silently mis-mapped funding column is far more expensive than thirty seconds of confirming.
- **The LLM can still be wrong.** It is constrained from inventing facts, but its *judgement* — a moat rating, a why-now argument — is opinion. That is why every rating shows its source icon and can be overridden.

## Ethical considerations

- **No black-box success prediction.** A model that scores founders on predicted outcomes encodes historical bias — which schools, which cities, which names got funded before — and launders it as objectivity. This tool rates *evidence about a company*, shows its reasoning, and lets a human disagree with every number.
- **Founders are not the user, but they are affected.** A tool that quietly rejects companies on unverifiable data does real harm. That is why unknown funding routes to human review instead of a silent rejection, and why red flags are shown rather than subtracted.
- **Terms of service and robots.txt are respected.** No third-party database is scraped. Homepage fetching is off by default, honours `robots.txt`, and sends an identifying User-Agent.
- **Data minimalism.** Only publicly available company information is stored. Founder data is limited to what the company publishes about itself professionally.
- **Demo data can never masquerade as real.** Separate dataset, `DEMO` prefix, banners on every page, and a warning inside the dossier the LLM sees.
- **The recommendation ceiling is a safety feature, not a limitation.** `INVESTIGATE` means "worth a conversation". A machine should not be able to say "invest".

## Recommended next integration

**A web-search API (Brave, Tavily or Bing) as `WebSearchAdapter`, followed by Dealroom.**

Why that order:

1. **Search is the only source that can actually *discover*.** Dealroom and Crunchbase verify companies you already suspect exist; search finds the pre-seed company that announced a €600k round in a regional newspaper last week — exactly the deal flow a €3M ceiling targets.
2. **The evidence model is already built for it.** A search result carries a URL, a title and a publication, which map onto `Evidence.source_url`, `source_title` and `source_type`, and thus onto the tier hierarchy. A funding announcement in reputable media enters as Tier 2 and immediately makes a company's funding verifiable.
3. **It is legally clean.** A search API is a licensed product with clear terms, unlike scraping a directory.

Concretely: a `discover(thesis)` method issuing queries built from the thesis (`"pre-seed" OR "seed" climate startup Germany 2026 raised`), each hit becoming a candidate with at least one Tier-2 source attached; then per-company verification queries (`"<company>" funding round announcement`) to move `total_funding_eur` from `UNVERIFIED` to `VERIFIED`. **Dealroom second**, as the authority for European early-stage funding, to reconcile amounts — where it disagrees with the press, the existing conflict detection already raises the flag.

---

*Built for a venture capital application case. The tool structures the research; the investment decision is human.*
