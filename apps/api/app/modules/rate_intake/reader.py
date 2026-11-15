from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from app.core.errors import AppError
from app.modules.rate_intake.normalise import clean

COLUMNS: tuple[str, ...] = (
    "row_type",
    "property_name",
    "destination",
    "room_type",
    "room_sleeps",
    "meal_plan",
    "guest_residence",
    "price_covers",
    "label",
    "valid_from",
    "valid_to",
    "currency",
    "amount",
    "charged_per",
    "rack_or_sto",
    "discount_percent",
    "vat",
    "child_amount",
    "child_ages",
    "min_nights",
    "notes",
)

EXAMPLE_MARKER = "EXAMPLE"


class Row(dict[str, Any]):

    line: int = 0


def _rows_from_xlsx(path: Path) -> list[list[Any]]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        return [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()


def _rows_from_csv(path: Path) -> list[list[Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [list(row) for row in csv.reader(handle)]


def read_sheet(path: str | Path) -> tuple[list[Row], list[str]]:
    path = Path(path)
    if not path.is_file():
        raise AppError(f"No such intake sheet: {path}")
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        raw = _rows_from_xlsx(path)
    elif path.suffix.lower() == ".csv":
        raw = _rows_from_csv(path)
    else:
        raise AppError(
            f"{path.suffix} is not a readable intake sheet. Save it as .xlsx or .csv."
        )
    if not raw:
        raise AppError("That sheet is empty.")

    header = [clean(cell).lower() for cell in raw[0]]
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        raise AppError(
            "The sheet is missing these columns: "
            + ", ".join(missing)
            + ". Start from docs/templates/rate-intake/hotel-rates.csv."
        )
    index = {column: header.index(column) for column in COLUMNS}

    rows: list[Row] = []
    skipped: list[str] = []
    for line, cells in enumerate(raw[1:], start=2):
        row = Row({name: cells[i] if i < len(cells) else None
                   for name, i in index.items()})
        row.line = line
        if not any(clean(value) for value in row.values()):
            continue
        if EXAMPLE_MARKER in clean(row["property_name"]).upper():
            skipped.append(f"row {line}: template example row")
            continue
        rows.append(row)
    return rows, skipped
