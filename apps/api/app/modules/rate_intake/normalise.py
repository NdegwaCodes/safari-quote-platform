from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

MEAL_PLAN_SYNONYMS: dict[str, str] = {
    "RO": "RO", "BO": "RO", "ROOM ONLY": "RO", "BED ONLY": "RO",
    "BB": "BB", "B&B": "BB", "B & B": "BB", "BED AND BREAKFAST": "BB",
    "BED & BREAKFAST": "BB",
    "HB": "HB", "HALF BOARD": "HB",
    "FB": "FB", "FULL BOARD": "FB",
    "AI": "AI", "ALL INCLUSIVE": "AI", "ALL-INCLUSIVE": "AI",
}


RESIDENCE_SYNONYMS: dict[str, str] = {
    "CITIZEN": "citizen", "KENYAN CITIZEN": "citizen", "KENYAN": "citizen",
    "EA_RESIDENT": "ea_resident", "EA RESIDENT": "ea_resident",
    "EAST AFRICAN CITIZEN": "ea_resident", "EAST AFRICAN RESIDENT": "ea_resident",
    "RESIDENT": "resident", "KENYA RESIDENT": "resident",
    "AFRICAN_CITIZEN": "african_citizen", "AFRICAN CITIZEN": "african_citizen",
    "NON_RESIDENT": "non_resident", "NON RESIDENT": "non_resident",
    "NON-RESIDENT": "non_resident", "NONRESIDENT": "non_resident",
    "INTERNATIONAL": "non_resident",
}

ROW_TYPES = frozenset({"RATE", "SUPPLEMENT", "EXTRA"})


def row_kind(row: object) -> str:
    if not isinstance(row, dict):
        return key(row) or "RATE"
    return key(row.get("row_type")) or "RATE"

RATE_BASES = {"room_per_night": "per_room", "person_per_night": "per_person"}
SUPPLEMENT_BASES = {
    "person_per_night": "per_person_per_night",
    "person_per_stay": "per_person",
    "room_per_night": "per_room_per_night",
    "room_per_stay": "per_room",
}


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split())


def key(value: object) -> str:
    return clean(value).upper()


def meal_plan_code(value: object) -> str | None:
    return MEAL_PLAN_SYNONYMS.get(key(value))


def residence_key(value: object) -> str | None:
    return RESIDENCE_SYNONYMS.get(key(value).replace("-", "_").replace(" ", "_")) or (
        RESIDENCE_SYNONYMS.get(key(value))
    )


_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def date_order(values: list[str]) -> str:
    day_first = month_first = 0
    for value in values:
        match = _DMY.match(clean(value))
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12:
            day_first += 1
        elif second > 12:
            month_first += 1
    if day_first and month_first:
        return "conflicting"
    if day_first:
        return "day_first"
    if month_first:
        return "month_first"
    return "ambiguous"


def parse_date(value: object, *, order: str) -> date | None:
    if value is None or clean(value) == "":
        return None
    if hasattr(value, "date") and not isinstance(value, str):
        return value.date()
    if isinstance(value, date):
        return value
    text = clean(value)
    iso = _ISO.match(text)
    if iso:
        return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    match = _DMY.match(text)
    if not match:
        return None
    a, b, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    day, month = (a, b) if order != "month_first" else (b, a)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = clean(value).replace(",", "").replace(" ", "")
    text = re.sub(r"^(KES|KSH|USD|EUR|GBP|\$|€|£)", "", text, flags=re.I)
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


def parse_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = clean(value)
    return int(text) if re.fullmatch(r"\d+", text) else None


def parse_percent(value: object) -> Decimal | None:
    if value is None or clean(value) == "":
        return None
    text = clean(value).rstrip("%")
    amount = parse_amount(text)
    return amount if amount is not None and 0 <= amount <= 100 else None


def parse_bool(value: object, *, default: bool) -> bool:
    text = key(value)
    if text in {"YES", "Y", "TRUE", "1", "MANDATORY", "COMPULSORY"}:
        return True
    if text in {"NO", "N", "FALSE", "0", "OPTIONAL"}:
        return False
    return default


_BAND = re.compile(r"^(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})$")
_ABOVE = re.compile(r"^(?:above|over|from)\s*(\d{1,2})(?:\s*(?:yrs?|years?))?$", re.I)
_UNDER = re.compile(r"^(?:under|below)\s*(\d{1,2})(?:\s*(?:yrs?|years?))?$", re.I)


def parse_child_ages(value: object) -> tuple[int, int] | None:
    text = clean(value)
    if not text:
        return None
    band = _BAND.match(text)
    if band:
        low, high = int(band.group(1)), int(band.group(2))
        return (low, high) if low <= high else (high, low)
    above = _ABOVE.match(text)
    if above:
        return (0, int(above.group(1)))
    under = _UNDER.match(text)
    if under:
        return (0, int(under.group(1)) - 1)
    return None


FOREIGN_DESTINATIONS = {
    "DAR ES SALAAM": "Tanzania",
    "KIGALI": "Rwanda",
}


def destination_country(name: object) -> str:
    return FOREIGN_DESTINATIONS.get(key(name), "Kenya")


def slugify(name: object) -> str:
    text = clean(name).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def near_duplicates(names: list[str]) -> dict[str, list[str]]:
    groups: dict[frozenset[str], list[str]] = {}
    for name in {clean(n) for n in names if clean(n)}:
        words = frozenset(
            w for w in re.split(r"[^a-z0-9]+", name.lower()) if len(w) > 2
        )
        groups.setdefault(words, []).append(name)
    out: dict[str, list[str]] = {}
    for _words, members in groups.items():
        if len(members) > 1:
            out[sorted(members)[0]] = sorted(members)
    cleaned = sorted({clean(n) for n in names if clean(n)})
    for name in cleaned:
        contained = [
            other
            for other in cleaned
            if other != name
            and set(re.split(r"[^a-z0-9]+", name.lower()))
            < set(re.split(r"[^a-z0-9]+", other.lower()))
        ]
        if contained:
            out.setdefault(name, sorted({name, *contained}))
    return out
