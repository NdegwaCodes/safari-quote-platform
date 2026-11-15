from __future__ import annotations

import calendar
import re
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

_MONEY = re.compile(
    r"""
    (?P<sign>-)?
    (?P<num>\d{1,3}(?:[.,]\d{3})+ | \d+(?:[.,]\d{1,2})? )
    """,
    re.VERBOSE,
)
_CURRENCY_TOKENS = {
    "KES": "KES",
    "KSH": "KES",
    "KSHS": "KES",
    "SH": "KES",
    "USD": "USD",
    "US$": "USD",
    "$": "USD",
    "EUR": "EUR",
    "GBP": "GBP",
}


def parse_money(text: str | None) -> Decimal | None:
    if not text:
        return None
    cleaned = text.replace("\n", " ").strip()
    if not cleaned:
        return None

    matches = _MONEY.findall(cleaned)
    if len(matches) != 1:
        return None
    sign, num = matches[0]

    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", num):
        num = num.replace(".", "").replace(",", "")
    else:
        num = num.replace(",", ".")

    try:
        value = Decimal(num)
    except InvalidOperation:
        return None
    if sign:
        value = -value
    return value if value > 0 else None


def parse_currency(text: str | None) -> str | None:
    if not text:
        return None
    upper = text.upper()
    found = {
        code
        for token, code in _CURRENCY_TOKENS.items()
        if re.search(rf"(?<![A-Z]){re.escape(token)}(?![A-Z])", upper)
    }
    return found.pop() if len(found) == 1 else None


_MEAL_PLANS = {
    "BO": "RO",
    "RO": "RO",
    "ROOM ONLY": "RO",
    "BED ONLY": "RO",
    "BB": "BB",
    "B&B": "BB",
    "B/B": "BB",
    "BED AND BREAKFAST": "BB",
    "BED & BREAKFAST": "BB",
    "HB": "HB",
    "H/B": "HB",
    "HALF BOARD": "HB",
    "FB": "FB",
    "F/B": "FB",
    "FULL BOARD": "FB",
    "AI": "AI",
    "ALL INCLUSIVE": "AI",
}


def parse_meal_plan(text: str | None) -> str | None:
    if not text:
        return None
    key = re.sub(r"\s+", " ", text.strip().upper())
    if key in _MEAL_PLANS:
        return _MEAL_PLANS[key]
    for token in re.findall(r"[A-Z&/]+", key):
        if token in _MEAL_PLANS:
            return _MEAL_PLANS[token]
    return None


_OCCUPANCY = {
    "SINGLE": 1,
    "SGL": 1,
    "SINGLE ROOM": 1,
    "DOUBLE": 2,
    "DBL": 2,
    "TWIN": 2,
    "DOUBLE/TWIN": 2,
    "DOUBLE ROOM": 2,
    "TRIPLE": 3,
    "TPL": 3,
    "TRIPLE ROOM": 3,
    "QUAD": 4,
    "QUADRUPLE": 4,
}


def parse_occupancy(text: str | None) -> int | None:
    if not text:
        return None
    key = re.sub(r"\s+", " ", text.strip().upper())
    if " OR " in key:
        return None
    if key in _OCCUPANCY:
        return _OCCUPANCY[key]
    for token in sorted(_OCCUPANCY, key=len, reverse=True):
        if re.search(rf"(?<![A-Z]){re.escape(token)}(?![A-Z])", key):
            return _OCCUPANCY[token]
    return None


_SEASONS = ("PEAK", "FESTIVE", "EASTER", "SHOULDER", "HIGH", "LOW", "MID", "GREEN")


def parse_season(text: str | None) -> str | None:
    if not text:
        return None
    upper = text.upper()
    for name in _SEASONS:
        if re.search(rf"(?<![A-Z]){name}(?![A-Z])", upper):
            return name.title()
    return None


_MONTHS = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS |= {m.upper(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS["SEPT"] = 9

_NUMERIC = re.compile(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})")
_NAMED = re.compile(
    r"(\d{1,2})(?:st|nd|rd|th)?\s*([A-Za-z]{3,9})\.?"
    r"(?:\s*(?:'(\d{2})|(\d{4})|(\d{2})(?![\d.,])))?"
)
_SEPARATORS = re.compile(r"\s*(?:-|–|—|to|until|till)\s*", re.IGNORECASE)


def _year(raw: str | None, *, default: int | None) -> int | None:
    if raw is None:
        return default
    value = int(raw)
    if value < 100:
        return 2000 + value
    return value


def _one_date(text: str, *, default_year: int | None) -> tuple[date | None, bool]:
    text = text.strip()
    m = _NUMERIC.search(text)
    if m:
        day, month, raw_year = m.group(1), m.group(2), m.group(3)
        year = _year(raw_year, default=default_year)
        if not year:
            return None, raw_year is not None
        try:
            return date(int(year), int(month), int(day)), raw_year is not None
        except ValueError:
            return None, raw_year is not None
    m = _NAMED.search(text)
    if m:
        day, name = m.group(1), m.group(2).upper()
        bare = m.group(5)
        if bare is not None and not (24 <= int(bare) <= 35):
            bare = None
        raw_year = m.group(3) or m.group(4) or bare
        month = _MONTHS.get(name) or _MONTHS.get(name[:3])
        year = _year(raw_year, default=default_year)
        if not month or not year:
            return None, raw_year is not None
        try:
            return date(year, month, int(day)), raw_year is not None
        except ValueError:
            return None, raw_year is not None
    return None, False


def parse_date_range(
    text: str | None, *, default_year: int | None = None
) -> tuple[date | None, date | None]:
    if not text:
        return None, None
    cleaned = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()

    parts = [p for p in _SEPARATORS.split(cleaned) if p.strip()]
    if len(parts) < 2:
        found = _NUMERIC.findall(cleaned)
        if len(found) == 2:
            parts = [
                f"{d}/{m}/{y}" for d, m, y in found  # noqa: E501
            ]
        else:
            return None, None

    dated = [p for p in parts if _NUMERIC.search(p) or _NAMED.search(p)]
    if len(dated) < 2:
        return None, None
    left_text, right_text = dated[0], dated[1]

    end, end_had_year = _one_date(right_text, default_year=default_year)
    start, start_had_year = _one_date(
        left_text, default_year=(end.year if end else default_year)
    )
    if start is None or end is None:
        return start, end
    if end >= start:
        return start, end

    try:
        if end_had_year and not start_had_year:
            return start.replace(year=start.year - 1), end
        return start, end.replace(year=end.year + 1)
    except ValueError:
        return start, None


_SEASON_LINE = re.compile(
    r"(?P<name>PEAK|FESTIVE|EASTER|SHOULDER|HIGH|LOW|MID|GREEN)\s+SEASON(?P<rest>[^\n]*)",
    re.IGNORECASE,
)


def season_windows(
    text: str, *, default_year: int | None = None
) -> dict[str, list[tuple[date, date]]]:
    found: dict[str, list[tuple[date, date]]] = {}
    for match in _SEASON_LINE.finditer(text or ""):
        name = match.group("name").title()
        windows: list[tuple[date, date]] = []
        for chunk in re.split(r";|&|\band\b", match.group("rest")):
            start, end = parse_date_range(chunk, default_year=default_year)
            if start and end:
                windows.append((start, end))
        if windows:
            found.setdefault(name, [])
            for window in windows:
                if window not in found[name]:
                    found[name].append(window)
    return found


_ANY_YEAR = re.compile(r"(?<![0-9])(20[2-3][0-9])(?![0-9])")


def document_year(text: str) -> int | None:
    counts = Counter(_ANY_YEAR.findall(text or ""))
    if not counts:
        return None
    most = max(counts.values())
    return min(int(year) for year, count in counts.items() if count == most)
