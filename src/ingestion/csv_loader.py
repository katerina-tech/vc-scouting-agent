"""CSV ingestion.

Every column is normalized on the way in and every populated field produces a
piece of ``Evidence``. A CSV cell is *not* a verified fact: unless the row also
carries a source URL for that field, the evidence is recorded as UNVERIFIED
with ``SourceType.USER_INPUT``. That is what keeps an uploaded spreadsheet from
silently becoming "truth".
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from ..models.enums import Dataset, SourceType, VerificationStatus
from ..models.evidence import Evidence
from ..models.startup import Startup
from ..normalization.company_normalizer import (
    clean_display_name,
    extract_domain,
    normalize_company_name,
    normalize_country,
    normalize_date,
    normalize_funding,
    normalize_sector,
    normalize_stage,
    normalize_url,
    normalize_year,
    parse_bool,
    split_list,
    infer_themes,
)
from .source_adapter import IngestionResult, SourceAdapter

#: Accepted CSV headers -> model field. Several spellings map to one field so a
#: Dealroom / Crunchbase export can be dropped in with minimal editing.
COLUMN_ALIASES: dict[str, str] = {
    "company": "company_name", "company_name": "company_name", "name": "company_name",
    "startup": "company_name", "organisation": "company_name", "organization": "company_name",
    "website": "website", "url": "website", "domain": "website", "homepage": "website",
    "country": "hq_country", "hq_country": "hq_country", "hq": "hq_country",
    "headquarters": "hq_country", "location": "hq_country",
    "city": "city", "hq_city": "city",
    "founded": "founded_year", "founded_year": "founded_year", "year_founded": "founded_year",
    "sector": "sector", "industry": "sector", "vertical": "sector", "category": "sector",
    "subsector": "subsector", "sub_sector": "subsector", "niche": "subsector",
    "stage": "stage", "funding_stage": "stage", "last_round_type": "stage", "round": "stage",
    "total_funding": "total_funding_eur", "total_funding_eur": "total_funding_eur",
    "funding": "total_funding_eur", "amount_raised": "total_funding_eur",
    "total_raised": "total_funding_eur",
    "last_round": "last_round_eur", "last_round_eur": "last_round_eur",
    "last_round_amount": "last_round_eur",
    "last_round_date": "last_round_date", "last_funding_date": "last_round_date",
    "investors": "investors", "lead_investor": "investors", "backers": "investors",
    "founders": "founders", "founder": "founders", "team": "founders",
    "founder_background": "founder_background", "founder_bio": "founder_background",
    "product": "product_summary", "product_summary": "product_summary",
    "description": "product_summary", "short_description": "product_summary",
    "business_model": "business_model", "model": "business_model", "revenue_model": "business_model",
    "customers": "customers", "clients": "customers",
    "traction": "traction_signals", "traction_signals": "traction_signals", "metrics": "traction_signals",
    "technology": "technology", "tech": "technology", "tech_stack": "technology",
    "moat": "technical_moat", "technical_moat": "technical_moat", "defensibility": "technical_moat",
    "competitors": "competitors", "competition": "competitors",
    "market": "market_size_signal", "market_size": "market_size_signal",
    "market_size_signal": "market_size_signal", "tam": "market_size_signal",
    "impact": "impact_signal", "impact_signal": "impact_signal", "sdg": "impact_signal",
    "why_now": "why_now_signal", "why_now_signal": "why_now_signal", "timing": "why_now_signal",
    "source": "source_urls", "sources": "source_urls", "source_url": "source_urls",
    "source_urls": "source_urls", "evidence_url": "source_urls",
    "active": "is_active", "is_active": "is_active", "status": "is_active",
    "notes": "notes", "comment": "notes",
    "funding_source_url": "funding_source_url",
    "funding_verified": "funding_verified",
}

LIST_FIELDS = {
    "investors", "founders", "customers", "traction_signals", "competitors", "source_urls",
}

#: A minimal, self-documenting template offered as a download in the UI.
TEMPLATE_COLUMNS: list[str] = [
    "company_name", "website", "hq_country", "city", "founded_year", "sector", "subsector",
    "stage", "total_funding_eur", "last_round_eur", "last_round_date", "investors",
    "founders", "founder_background", "product_summary", "business_model", "customers",
    "traction_signals", "technology", "technical_moat", "competitors", "market_size_signal",
    "impact_signal", "why_now_signal", "is_active", "source_urls", "funding_source_url",
    "funding_verified", "notes",
]


def normalize_headers(columns: list[str]) -> dict[str, str]:
    """Map the file's actual headers onto model field names."""
    mapping: dict[str, str] = {}
    for col in columns:
        key = str(col).strip().lower().replace(" ", "_").replace("-", "_")
        if key in COLUMN_ALIASES:
            mapping[col] = COLUMN_ALIASES[key]
    return mapping


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if pd.isna(value) if not isinstance(value, (list, dict, set)) else False:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


def row_to_startup(
    row: dict[str, Any],
    dataset: Dataset = Dataset.REAL,
    adapter_name: str = "csv",
    default_source_type: SourceType | None = None,
) -> tuple[Startup | None, list[Evidence], list[str]]:
    """Convert one normalized row into a Startup plus its evidence trail."""
    warnings: list[str] = []
    name = clean_display_name(_clean(row.get("company_name")))
    if not name:
        return None, [], ["Row skipped: no company name."]

    website = normalize_url(_clean(row.get("website")))
    funding = normalize_funding(_clean(row.get("total_funding_eur")))
    last_round = normalize_funding(_clean(row.get("last_round_eur")))
    country = normalize_country(_clean(row.get("hq_country")))

    sector = normalize_sector(_clean(row.get("sector")))
    subsector = normalize_sector(_clean(row.get("subsector")))
    product = _clean(row.get("product_summary"))
    impact = _clean(row.get("impact_signal"))

    startup = Startup(
        company_name=name,
        normalized_name=normalize_company_name(name),
        website=website,
        domain=extract_domain(website),
        dataset=dataset,
        hq_country=country,
        hq_country_raw=_clean(row.get("hq_country")),
        city=clean_display_name(_clean(row.get("city"))) or None,
        founded_year=normalize_year(_clean(row.get("founded_year"))),
        sector=sector,
        subsector=subsector,
        themes=infer_themes(sector, subsector, product, impact),
        stage=normalize_stage(_clean(row.get("stage"))),
        stage_raw=_clean(row.get("stage")),
        is_active=parse_bool(_clean(row.get("is_active"))),
        total_funding_eur=funding["amount_eur"],
        total_funding_raw=funding["raw"],
        fx_note=funding["fx_note"],
        last_round_eur=last_round["amount_eur"],
        last_round_raw=last_round["raw"],
        last_round_date=normalize_date(_clean(row.get("last_round_date"))),
        investors=split_list(_clean(row.get("investors"))),
        founders=split_list(_clean(row.get("founders"))),
        founder_background=_clean(row.get("founder_background")),
        product_summary=product,
        business_model=_clean(row.get("business_model")),
        customers=split_list(_clean(row.get("customers"))),
        traction_signals=split_list(_clean(row.get("traction_signals"))),
        technology=_clean(row.get("technology")),
        technical_moat=_clean(row.get("technical_moat")),
        competitors=split_list(_clean(row.get("competitors"))),
        market_size_signal=_clean(row.get("market_size_signal")),
        impact_signal=impact,
        why_now_signal=_clean(row.get("why_now_signal")),
        source_urls=[u for u in (normalize_url(u) for u in split_list(_clean(row.get("source_urls")))) if u],
        notes=_clean(row.get("notes")) or "",
        source_adapter=adapter_name,
        raw_record={k: _clean(v) for k, v in row.items()},
    )

    if funding["raw"] and funding["amount_eur"] is None:
        warnings.append(
            f"{name}: could not parse funding value {funding['raw']!r} — left as unknown."
        )

    evidence = _evidence_for_row(startup, row, adapter_name, default_source_type)
    return startup, evidence, warnings


def _evidence_for_row(
    startup: Startup,
    row: dict[str, Any],
    adapter_name: str,
    default_source_type: SourceType | None = None,
) -> list[Evidence]:
    """One Evidence per populated field, with the row's source URL if given."""
    generic_sources = startup.source_urls
    primary_source = generic_sources[0] if generic_sources else None
    funding_source = normalize_url(_clean(row.get("funding_source_url")))
    funding_verified_flag = parse_bool(_clean(row.get("funding_verified")))

    out: list[Evidence] = []

    def add(field_name: str, value, *, url: str | None, source_type: SourceType, status, note: str):
        if value in (None, "", [], {}):
            return
        out.append(
            Evidence(
                startup_id=startup.id,
                field_name=field_name,
                value=value,
                source_url=url,
                source_title=(f"{adapter_name} import" if not url else None),
                source_type=source_type,
                verification_status=status,
                evidence_note=note,
                added_by=adapter_name,
            )
        )

    tracked_fields = [
        ("company_name", startup.company_name), ("website", startup.website),
        ("hq_country", startup.hq_country), ("city", startup.city),
        ("founded_year", startup.founded_year), ("sector", startup.sector),
        ("subsector", startup.subsector), ("stage", startup.stage.value),
        ("last_round_eur", startup.last_round_eur), ("last_round_date", startup.last_round_date),
        ("investors", startup.investors), ("founders", startup.founders),
        ("founder_background", startup.founder_background),
        ("product_summary", startup.product_summary), ("business_model", startup.business_model),
        ("customers", startup.customers), ("traction_signals", startup.traction_signals),
        ("technology", startup.technology), ("technical_moat", startup.technical_moat),
        ("competitors", startup.competitors), ("market_size_signal", startup.market_size_signal),
        ("impact_signal", startup.impact_signal), ("why_now_signal", startup.why_now_signal),
        ("is_active", startup.is_active), ("themes", startup.themes),
    ]

    # The operator declares what kind of source the file came from, which sets
    # the tier: an official EIC list is Tier 1, a directory export is Tier 3.
    row_source_type = default_source_type or SourceType.STARTUP_DATABASE

    for field_name, value in tracked_fields:
        if primary_source:
            add(field_name, value, url=primary_source,
                source_type=row_source_type,
                status=VerificationStatus.UNVERIFIED,
                note=(
                    f"Imported from a {row_source_type.tier.label.lower()} file; the "
                    "row-level source URL applies to the whole record."
                ))
        else:
            add(field_name, value, url=None,
                source_type=SourceType.USER_INPUT,
                status=VerificationStatus.UNVERIFIED,
                note="Imported from a file with no source URL — unverified by design.")

    # Funding is treated more strictly than anything else.
    if startup.total_funding_eur is not None:
        if funding_source:
            status = (
                VerificationStatus.VERIFIED if funding_verified_flag is not False
                else VerificationStatus.UNVERIFIED
            )
            add(
                "total_funding_eur", startup.total_funding_eur, url=funding_source,
                source_type=SourceType.FUNDING_ANNOUNCEMENT, status=status,
                note=f"Funding source supplied in the import ({startup.total_funding_raw}).",
            )
        else:
            add(
                "total_funding_eur", startup.total_funding_eur, url=None,
                source_type=SourceType.USER_INPUT, status=VerificationStatus.UNVERIFIED,
                note=(
                    "Funding figure imported without a source URL. It is NOT treated as "
                    "verified and cannot on its own make the company eligible."
                ),
            )
    return out


def read_table(
    content: bytes | str | None = None,
    path: str | None = None,
    filename: str = "",
) -> tuple["pd.DataFrame | None", str]:
    """Read a CSV, TSV or Excel file into a DataFrame. Returns (frame, error).

    Delimiter and encoding are sniffed, because real exports from European
    sources are frequently semicolon-separated and Latin-1 encoded.
    """
    name = (filename or path or "").lower()
    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            source = io.BytesIO(content) if isinstance(content, bytes) else path
            return pd.read_excel(source), ""

        if content is not None:
            raw = content if isinstance(content, bytes) else content.encode("utf-8")
            for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return None, "Could not decode the file as UTF-8 or Latin-1."
            # sep=None + the python engine sniffs , ; \t automatically
            return pd.read_csv(io.StringIO(text), sep=None, engine="python"), ""

        if path is not None:
            return pd.read_csv(path, sep=None, engine="python"), ""
    except Exception as exc:  # noqa: BLE001 — every parse failure goes to the UI
        return None, f"Could not read the file: {exc}"

    return None, "No file content or path supplied."


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    """Best-guess ``model_field -> source_column``, for the mapping UI to preload."""
    header_map = normalize_headers(columns)  # source_column -> model_field
    suggestion: dict[str, str] = {}
    for source_column, model_field in header_map.items():
        suggestion.setdefault(model_field, source_column)
    return suggestion


def apply_mapping(frame: "pd.DataFrame", mapping: dict[str, str]) -> "pd.DataFrame":
    """Rename using an explicit ``model_field -> source_column`` mapping."""
    rename = {source: field for field, source in mapping.items() if source}
    keep = [c for c in frame.columns if c in rename]
    return frame[keep].rename(columns=rename)


class CSVSourceAdapter(SourceAdapter):
    name = "csv"
    label = "File import"
    source_type = SourceType.STARTUP_DATABASE

    def fetch(self, *, content: bytes | str | None = None, path: str | None = None,
              dataset: Dataset = Dataset.REAL, filename: str = "",
              mapping: dict[str, str] | None = None,
              source_type: SourceType | None = None,
              adapter_label: str | None = None,
              **_: Any) -> IngestionResult:
        result = IngestionResult()

        frame, error = read_table(content=content, path=path, filename=filename)
        if frame is None:
            result.errors.append(error)
            return result
        if frame.empty:
            result.warnings.append("The file contained no rows.")
            return result

        if mapping:
            # An explicit mapping from the import wizard: no guessing at all.
            if not mapping.get("company_name"):
                result.errors.append("Map a column to 'Company name' before importing.")
                return result
            frame = apply_mapping(frame, mapping)
        else:
            header_map = normalize_headers(list(frame.columns))
            if "company_name" not in header_map.values():
                result.errors.append(
                    "No recognisable company-name column found. Use the column-mapping "
                    "step to say which column holds the company name."
                )
                return result
            unmapped = [c for c in frame.columns if c not in header_map]
            if unmapped:
                result.warnings.append(
                    f"Ignored {len(unmapped)} unrecognised column(s): "
                    + ", ".join(map(str, unmapped[:8]))
                    + ("…" if len(unmapped) > 8 else "")
                )
            frame = frame.rename(columns=header_map)

        result.rows_seen = len(frame)
        adapter_name = adapter_label or self.name

        for record in frame.to_dict(orient="records"):
            startup, evidence, warnings = row_to_startup(
                record, dataset=dataset, adapter_name=adapter_name,
                default_source_type=source_type,
            )
            result.warnings.extend(warnings)
            if startup is not None:
                result.startups.append(startup)
                result.evidence.extend(evidence)

        return result


def template_csv() -> str:
    """A blank template with the supported headers, offered as a download."""
    return ",".join(TEMPLATE_COLUMNS) + "\n"
