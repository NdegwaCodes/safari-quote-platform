from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

import pdfplumber

from app.core.storage import resolve
from app.integrations.rate_extraction import (
    ExtractedRateRow,
    ExtractionHint,
    ExtractionResult,
)
from app.modules.supplier_docs.parsing import (
    parse_currency,
    parse_date_range,
    parse_meal_plan,
    parse_money,
    parse_occupancy,
    parse_season,
)

_PHRASE_GAP = 10.0
_LINE_TOL = 3.0
_MIN_MEAL_CODES = 2
_COLUMN_TOL = 25.0
_MIN_ALIGNED_PRICES = 2
_PER_PERSON = re.compile(r"per\s+person|pp\s+sharing|per\s+pax", re.IGNORECASE)
_PER_ROOM = re.compile(r"per\s+room", re.IGNORECASE)


def _is_fragmented(line: list[dict]) -> bool:
    if len(line) < 6:
        return False
    singles = sum(
        1
        for word in line
        if len(text := str(word["text"]).strip()) == 1 and text.isalnum()
    )
    return singles / len(line) > 0.4


def _looks_like_a_room_name(text: str) -> bool:
    if parse_money(text) is not None or parse_occupancy(text) is not None:
        return False
    if parse_meal_plan(text) is not None or parse_season(text) is not None:
        return False
    return bool(re.search(r"[A-Za-z]{3}", text))


@dataclass(frozen=True)
class _Span:

    text: str
    x0: float
    x1: float

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2


def _lines(words: list[dict]) -> list[list[dict]]:
    rows: dict[float, list[dict]] = defaultdict(list)
    for word in words:
        rows[round(float(word["top"]) / _LINE_TOL)].append(word)
    return [
        sorted(rows[key], key=lambda w: float(w["x0"])) for key in sorted(rows)
    ]


def _phrases(line: list[dict]) -> list[_Span]:
    spans: list[_Span] = []
    for word in line:
        x0, x1, text = float(word["x0"]), float(word["x1"]), str(word["text"])
        both_money = bool(
            spans
            and parse_money(spans[-1].text) is not None
            and parse_money(text) is not None
        )
        if spans and not both_money and x0 - spans[-1].x1 <= _PHRASE_GAP:
            previous = spans.pop()
            spans.append(_Span(f"{previous.text} {text}", previous.x0, x1))
        else:
            spans.append(_Span(text, x0, x1))
    return spans


def _nearest(spans: list[_Span], centre: float) -> _Span | None:
    if not spans:
        return None
    return min(spans, key=lambda s: abs(s.centre - centre))


class BlockRateExtractor:

    name = "pdf-block"

    def supports(self, content_type: str, filename: str) -> bool:
        return content_type == "application/pdf" or filename.lower().endswith(".pdf")

    def extract(self, path: str, hint: ExtractionHint) -> ExtractionResult:
        result = ExtractionResult(provider=self.name)
        try:
            absolute = resolve(path)
        except ValueError as exc:  # pragma: no cover - defensive
            result.warnings.append(str(exc))
            return result

        try:
            with pdfplumber.open(absolute) as pdf:
                result.page_count = len(pdf.pages)
                for number, page in enumerate(pdf.pages, start=1):
                    result.rows.extend(self._read_page(page, hint, page_number=number))
        except Exception as exc:  # noqa: BLE001 - one bad file must not 500
            result.warnings.append(f"could not read the PDF: {type(exc).__name__}: {exc}")
        return result

    def _read_page(
        self, page: object, hint: ExtractionHint, *, page_number: int
    ) -> list[ExtractedRateRow]:
        words = page.extract_words()  # type: ignore[attr-defined]
        if not words:
            return []

        page_text = " ".join(str(w["text"]) for w in words)
        page_currency = parse_currency(page_text)
        per_person = bool(_PER_PERSON.search(page_text)) and not _PER_ROOM.search(
            page_text
        )

        room: str | None = None
        meal_columns: list[_Span] = []
        season_bands: list[_Span] = []
        date_bands: list[_Span] = []

        out: list[ExtractedRateRow] = []
        for line in _lines(words):
            spans = _phrases(line)
            if not spans:
                continue
            if _is_fragmented(line):
                continue

            seasons = [s for s in spans if parse_season(s.text)]
            dates = [s for s in spans if all(parse_date_range(s.text))]
            meals = [s for s in spans if parse_meal_plan(s.text)]
            monies = [s for s in spans if parse_money(s.text) is not None]

            if dates and not monies:
                date_bands = dates
                continue
            if seasons and not monies and not dates:
                season_bands = seasons
                continue
            if len(meals) >= _MIN_MEAL_CODES and not monies:
                meal_columns = meals
                leftmost = spans[0]
                if leftmost not in meals and parse_occupancy(leftmost.text) is None:
                    room = leftmost.text
                continue

            if not monies or not meal_columns:
                continue
            aligned = [
                money
                for money in monies
                if (nearest := _nearest(meal_columns, money.centre)) is not None
                and abs(nearest.centre - money.centre) <= _COLUMN_TOL
            ]
            if len(aligned) < _MIN_ALIGNED_PRICES:
                continue
            occupancy = parse_occupancy(spans[0].text)
            row_room = room
            if occupancy is None:
                if not _looks_like_a_room_name(spans[0].text):
                    continue
                row_room = spans[0].text

            for money in aligned:
                amount = parse_money(money.text)
                if amount is None:
                    continue
                meal_span = _nearest(meal_columns, money.centre)
                date_span = _nearest(date_bands, money.centre)
                season_span = _nearest(season_bands, money.centre)

                start, end = (
                    parse_date_range(date_span.text) if date_span else (None, None)
                )
                meal_plan = (
                    parse_meal_plan(meal_span.text) if meal_span else None
                ) or hint.default_meal_plan

                warnings: list[str] = []
                if meal_plan is None:
                    warnings.append("could not read the meal plan for this column")
                if not (start and end):
                    warnings.append("could not read the season window for this block")
                if row_room is None:
                    warnings.append("could not read the room type for this block")
                if occupancy is None:
                    warnings.append(
                        "the sheet does not say how many guests this price covers"
                    )
                if per_person:
                    warnings.append(
                        "this sheet quotes rates PER PERSON, not per room - confirm "
                        "the basis before storing it as a room rate"
                    )

                currency = page_currency or hint.default_currency
                if currency is None:
                    warnings.append("the sheet does not state a currency")

                out.append(
                    ExtractedRateRow(
                        room_type=row_room,
                        meal_plan=meal_plan,
                        occupancy=occupancy,
                        season_name=(
                            parse_season(season_span.text) if season_span else None
                        ),
                        effective_from=start,
                        effective_to=end,
                        currency=currency,
                        rate_per_night=amount,
                        confidence=round(max(0.1, 1.0 - 0.25 * len(warnings)), 2),
                        source_note=(
                            f"page {page_number}: {row_room} / {spans[0].text} / "
                            f"{meal_span.text if meal_span else '?'} = {money.text}"
                        )[:500],
                        page=page_number,
                        warnings=tuple(warnings),
                    )
                )
        return out
