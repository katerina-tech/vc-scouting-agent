"""Deterministic normalization of everything that arrives messy.

Principle: **normalize, never discard.** Each function returns the normalized
value; the caller keeps the raw string alongside it on the ``Startup`` model so
a number can always be traced back to what the source literally said.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from urllib.parse import urlparse

from ..models.enums import Stage
from ..models.thesis import EUROPE_COUNTRIES

# --------------------------------------------------------------------------- #
# Company names
# --------------------------------------------------------------------------- #

#: Legal-form suffixes stripped when building a comparison key. Longest first.
LEGAL_SUFFIXES: tuple[str, ...] = (
    "gmbh and co kg", "gmbh und co kg", "s r l", "s p a", "b v", "n v", "a s",
    "sp z o o", "s a s", "s a", "s l", "ug haftungsbeschrankt", "ug",
    "gmbh", "mbh", "ag", "ltd", "limited", "llc", "inc", "incorporated",
    "corp", "corporation", "plc", "oy", "oyj", "ab", "aps", "as", "bv", "nv",
    "sarl", "sas", "srl", "spa", "sl", "sa", "kft", "zrt", "doo", "ou", "sia",
    "uab", "ehf", "kg", "eg", "vof", "cvba", "bvba", "co", "company",
)

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WS_RE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def normalize_company_name(name: str | None) -> str:
    """Lowercase, de-accented, punctuation-free, legal-suffix-free comparison key.

    ``"Söl.ar Energy GmbH & Co. KG"`` -> ``"solar energy"``
    """
    if not name:
        return ""
    text = strip_accents(str(name)).lower()
    text = text.replace("&", " and ")
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()

    changed = True
    while changed and text:
        changed = False
        for suffix in LEGAL_SUFFIXES:
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return text


def clean_display_name(name: str | None) -> str:
    if not name:
        return ""
    return _WS_RE.sub(" ", str(name)).strip(" ,;.\t\n")


# --------------------------------------------------------------------------- #
# URLs and domains
# --------------------------------------------------------------------------- #

#: A hostname: dot-separated labels, optional port, no spaces, real TLD-ish ending.
_HOSTNAME_RE = re.compile(
    r"^(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}(?::\d{1,5})?$"
)


def normalize_url(url: str | None) -> str | None:
    """Return a canonical ``https://host/path`` form, or None if unusable."""
    if not url or not str(url).strip():
        return None
    raw = str(url).strip()
    if raw.lower() in {"n/a", "na", "none", "-", "unknown"}:
        return None
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None
    if not parsed.netloc or not _HOSTNAME_RE.match(parsed.netloc):
        # "not a url at all" parses into a netloc but is not a hostname.
        return None
    host = parsed.netloc.lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"https://{host}{path}" if path else f"https://{host}"


def extract_domain(url: str | None) -> str | None:
    """``https://www.Acme.io/about`` -> ``acme.io``"""
    normalized = normalize_url(url)
    if not normalized:
        return None
    host = urlparse(normalized).netloc.lower()
    return host or None


# --------------------------------------------------------------------------- #
# Countries
# --------------------------------------------------------------------------- #

COUNTRY_ALIASES: dict[str, str] = {
    "uk": "United Kingdom", "u k": "United Kingdom", "gb": "United Kingdom",
    "great britain": "United Kingdom", "england": "United Kingdom",
    "scotland": "United Kingdom", "wales": "United Kingdom",
    "united kingdom of great britain and northern ireland": "United Kingdom",
    "de": "Germany", "deutschland": "Germany", "ger": "Germany",
    "fr": "France", "es": "Spain", "espana": "Spain",
    "it": "Italy", "italia": "Italy",
    "nl": "Netherlands", "the netherlands": "Netherlands", "holland": "Netherlands",
    "se": "Sweden", "sverige": "Sweden",
    "dk": "Denmark", "danmark": "Denmark",
    "fi": "Finland", "suomi": "Finland",
    "no": "Norway", "norge": "Norway",
    "pl": "Poland", "polska": "Poland",
    "pt": "Portugal", "ie": "Ireland", "eire": "Ireland",
    "at": "Austria", "osterreich": "Austria",
    "ch": "Switzerland", "schweiz": "Switzerland", "suisse": "Switzerland",
    "be": "Belgium", "belgie": "Belgium", "belgique": "Belgium",
    "cz": "Czechia", "czech republic": "Czechia", "ceska republika": "Czechia",
    "gr": "Greece", "hellas": "Greece",
    "ee": "Estonia", "eesti": "Estonia",
    "lv": "Latvia", "lt": "Lithuania", "ro": "Romania", "bg": "Bulgaria",
    "hr": "Croatia", "si": "Slovenia", "sk": "Slovakia", "hu": "Hungary",
    "rs": "Serbia", "ua": "Ukraine", "is": "Iceland", "island": "Iceland",
    "lu": "Luxembourg", "mt": "Malta", "cy": "Cyprus",
    "us": "United States", "usa": "United States", "u s a": "United States",
    "united states of america": "United States",
    "uae": "United Arab Emirates", "ca": "Canada", "il": "Israel",
    "sg": "Singapore", "in": "India", "au": "Australia",
}


def normalize_country(country: str | None) -> str | None:
    """Map free-text country input onto a canonical country name."""
    if not country or not str(country).strip():
        return None
    raw = strip_accents(str(country)).lower().strip()
    raw = _PUNCT_RE.sub(" ", raw)
    raw = _WS_RE.sub(" ", raw).strip()
    if not raw or raw in {"n a", "na", "none", "unknown", "-"}:
        return None
    if raw in COUNTRY_ALIASES:
        return COUNTRY_ALIASES[raw]
    for canonical in EUROPE_COUNTRIES:
        if strip_accents(canonical).lower() == raw:
            return canonical
    return " ".join(part.capitalize() for part in raw.split())


def is_european(country: str | None) -> bool | None:
    """True / False / None when the country cannot be determined."""
    normalized = normalize_country(country)
    if normalized is None:
        return None
    return normalized in EUROPE_COUNTRIES


# --------------------------------------------------------------------------- #
# Money
# --------------------------------------------------------------------------- #

#: Static reference rates (units of currency per 1 EUR). Deliberately static and
#: documented rather than silently live: reproducibility beats freshness for a
#: research tool, and every converted value records the rate used.
FX_RATES_PER_EUR: dict[str, float] = {
    "EUR": 1.0, "USD": 1.08, "GBP": 0.85, "CHF": 0.95, "SEK": 11.4,
    "NOK": 11.6, "DKK": 7.46, "PLN": 4.3, "CZK": 25.0, "HUF": 390.0,
    "RON": 4.97, "BGN": 1.96, "ISK": 150.0, "ILS": 4.0, "CAD": 1.47,
}
FX_RATES_AS_OF = "2024-06-01 (static reference rates — see README)"

CURRENCY_SYMBOLS: dict[str, str] = {
    "€": "EUR", "$": "USD", "£": "GBP", "chf": "CHF", "kr": "SEK", "zł": "PLN",
}

_MULTIPLIERS: dict[str, float] = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6, "mio": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
}

# The grouped alternative requires at least ONE separator (`+`, not `*`).
# With `*` it happily matched the first three digits of a plain "1400000" and
# returned 140 — a silent, catastrophic misreading of a funding figure.
_AMOUNT_RE = re.compile(
    r"(?P<num>\d{1,3}(?:[.,\s]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"\s*(?P<mult>k|mm|mn|m|bn|b|thousand|million|millions|mio|billion)?",
    flags=re.IGNORECASE,
)


def _parse_number(num_text: str) -> float | None:
    """Handle 1,800,000 / 1.800.000 / 1 800 000 / 1.8 / 1,8 correctly."""
    text = num_text.strip().replace(" ", "")
    if not text:
        return None
    has_comma, has_dot = "," in text, "." in text
    if has_comma and has_dot:
        # The right-most separator is the decimal one.
        decimal_sep = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_sep = "." if decimal_sep == "," else ","
        text = text.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif has_comma:
        parts = text.split(",")
        text = text.replace(",", "") if len(parts[-1]) == 3 and len(parts) > 1 else text.replace(",", ".")
    elif has_dot:
        parts = text.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[-1]) == 3 and len(parts[0]) <= 3 and parts[0] != "0"):
            # 1.800.000 or 1.800 -> thousands separator
            if len(parts) > 2:
                text = text.replace(".", "")
    try:
        return float(text)
    except ValueError:
        return None


def detect_currency(text: str) -> str | None:
    lowered = text.lower()
    for symbol, code in CURRENCY_SYMBOLS.items():
        if symbol in lowered:
            return code
    match = re.search(r"\b(eur|usd|gbp|chf|sek|nok|dkk|pln|czk|huf|ron|bgn|isk|ils|cad)\b", lowered)
    return match.group(1).upper() if match else None


def parse_money(value: object, default_currency: str = "EUR") -> tuple[float | None, str, str | None]:
    """Parse a funding figure into ``(amount, currency, raw_text)``.

    Accepts ``"€1.8M"``, ``"1,800,000 EUR"``, ``"$2m"``, ``"1.5m GBP"``,
    ``1800000``, ``"unknown"``. Returns ``(None, currency, raw)`` when the value
    cannot be parsed — never a guess.
    """
    if value is None:
        return None, default_currency, None
    if isinstance(value, bool):
        return None, default_currency, str(value)
    if isinstance(value, (int, float)):
        amount = float(value)
        return (amount if amount >= 0 else None), default_currency, str(value)

    raw = str(value).strip()
    if not raw or raw.lower() in {"unknown", "n/a", "na", "none", "-", "undisclosed", "?"}:
        return None, default_currency, raw or None

    currency = detect_currency(raw) or default_currency
    match = _AMOUNT_RE.search(raw)
    if not match:
        return None, currency, raw

    amount = _parse_number(match.group("num"))
    if amount is None:
        return None, currency, raw

    mult = (match.group("mult") or "").lower()
    if mult:
        amount *= _MULTIPLIERS.get(mult, 1.0)
    return amount, currency, raw


def to_eur(amount: float | None, currency: str) -> tuple[float | None, str | None]:
    """Convert to EUR using the static reference table. Returns (value, note)."""
    if amount is None:
        return None, None
    code = (currency or "EUR").upper()
    if code == "EUR":
        return round(amount, 2), None
    rate = FX_RATES_PER_EUR.get(code)
    if rate is None or rate == 0:
        return None, f"Unknown currency '{code}' — value left unconverted."
    # Whole euros: cents on a funding round are false precision, and the static
    # rate is far less accurate than the rounding anyway.
    converted = float(round(amount / rate))
    return converted, f"Converted from {amount:,.0f} {code} at {rate} {code}/EUR ({FX_RATES_AS_OF})."


def normalize_funding(value: object, default_currency: str = "EUR") -> dict:
    """One-call helper returning amount_eur, raw text and an FX note."""
    amount, currency, raw = parse_money(value, default_currency)
    amount_eur, note = to_eur(amount, currency)
    return {"amount_eur": amount_eur, "currency": currency, "raw": raw, "fx_note": note}


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d", "%b %Y", "%B %Y", "%Y-%m", "%Y")


def normalize_date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "n/a", "na", "none", "-"}:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def normalize_year(value: object) -> int | None:
    if value is None or value == "":
        return None
    match = re.search(r"(19|20)\d{2}", str(value))
    if not match:
        return None
    year = int(match.group(0))
    current = datetime.now().year
    return year if 1900 <= year <= current + 1 else None


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #

STAGE_ALIASES: dict[str, Stage] = {
    "pre seed": Stage.PRE_SEED, "preseed": Stage.PRE_SEED, "pre-seed": Stage.PRE_SEED,
    "presed": Stage.PRE_SEED, "angel": Stage.PRE_SEED, "friends and family": Stage.PRE_SEED,
    "idea": Stage.PRE_SEED, "formation": Stage.PRE_SEED,
    "seed": Stage.SEED, "seed round": Stage.SEED, "seed stage": Stage.SEED,
    "seed extension": Stage.SEED, "pre a": Stage.SEED, "pre series a": Stage.SEED,
    "series a": Stage.SERIES_A, "a": Stage.SERIES_A, "series a1": Stage.SERIES_A,
    "series b": Stage.SERIES_B_PLUS, "series c": Stage.SERIES_B_PLUS,
    "series d": Stage.SERIES_B_PLUS, "growth": Stage.SERIES_B_PLUS,
    "late stage": Stage.SERIES_B_PLUS, "ipo": Stage.SERIES_B_PLUS,
    "grant": Stage.GRANT_FUNDED, "grant funded": Stage.GRANT_FUNDED,
    "eic accelerator": Stage.GRANT_FUNDED, "non dilutive": Stage.GRANT_FUNDED,
    "bootstrapped": Stage.BOOTSTRAPPED, "self funded": Stage.BOOTSTRAPPED,
    "revenue funded": Stage.BOOTSTRAPPED,
}


def normalize_stage(value: object) -> Stage:
    if value is None:
        return Stage.UNKNOWN
    if isinstance(value, Stage):
        return value
    raw = strip_accents(str(value)).lower().strip()
    raw = _PUNCT_RE.sub(" ", raw)
    raw = _WS_RE.sub(" ", raw).strip()
    if not raw:
        return Stage.UNKNOWN
    if raw in STAGE_ALIASES:
        return STAGE_ALIASES[raw]
    try:
        return Stage(raw.upper().replace(" ", "_"))
    except ValueError:
        pass
    # Substring fallback, but only for aliases distinctive enough that a
    # partial match is meaningful — otherwise "blah" would match the alias "a".
    for alias, stage in STAGE_ALIASES.items():
        if len(alias) >= 4 and re.search(rf"\b{re.escape(alias)}\b", raw):
            return stage
    return Stage.UNKNOWN


# --------------------------------------------------------------------------- #
# Sector taxonomy -> thesis themes
# --------------------------------------------------------------------------- #

#: Keyword -> canonical theme. Intentionally conservative: a sector that does
#: not clearly map stays "Other" rather than being forced into a theme.
SECTOR_THEME_KEYWORDS: dict[str, list[str]] = {
    "Climate": [
        "climate", "carbon", "co2", "decarbon", "emission", "energy", "renewable",
        "solar", "wind", "battery", "storage", "grid", "cleantech", "greentech",
        "sustainab", "circular", "recycl", "waste", "water", "biodiversity",
        "agritech", "agtech", "food system", "alternative protein", "mobility",
        "ev charging", "heat pump", "geothermal", "hydrogen", "esg",
    ],
    "Health": [
        "health", "medtech", "medical", "clinical", "patient", "hospital",
        "diagnos", "therap", "biotech", "pharma", "drug", "mental health",
        "wellbeing", "care", "elderly", "digital health", "telemedicine",
        "femtech", "life science", "genomic", "oncology", "nurse",
    ],
    "Economic Empowerment": [
        "fintech", "financial inclusion", "banking", "credit", "lending",
        "savings", "payments", "insurtech", "pension", "wage", "payroll",
        "employment", "jobs", "hiring", "reskilling", "upskilling", "edtech",
        "education", "training", "workforce", "gig", "migrant", "refugee",
        "housing", "affordab", "sme lending", "microfinance", "poverty",
        "underbanked", "social mobility",
    ],
}


def infer_themes(*texts: str | None) -> list[str]:
    """Map sector / product text onto thesis themes. Returns [] when unclear."""
    blob = " ".join(strip_accents(t).lower() for t in texts if t)
    if not blob.strip():
        return []
    themes: list[str] = []
    for theme, keywords in SECTOR_THEME_KEYWORDS.items():
        if any(kw in blob for kw in keywords):
            themes.append(theme)
    return themes


def normalize_sector(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    text = _WS_RE.sub(" ", str(value).strip())
    return text[:1].upper() + text[1:]


def split_list(value: object, separators: str = ";|,") -> list[str]:
    """Split a delimited CSV cell into a clean list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [clean_display_name(str(v)) for v in value if str(v).strip()]
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "na", "none", "-", "unknown"}:
        return []
    parts = re.split(f"[{re.escape(separators)}]", text)
    return [clean_display_name(p) for p in parts if p and p.strip()]


def parse_bool(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "active", "operating"}:
        return True
    if text in {"false", "no", "n", "0", "inactive", "closed", "dead", "acquired"}:
        return False
    return None
