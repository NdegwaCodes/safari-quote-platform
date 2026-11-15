from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class ExtractionHint:

    residence_category: str | None = None
    rate_kind: str | None = None
    default_currency: str | None = None
    default_meal_plan: str | None = None
    supplier_discount_pct: Decimal | None = None
    vat_inclusive: bool = True
    vat_pct: Decimal = Decimal("16")


@dataclass(frozen=True)
class ExtractedRateRow:

    room_type: str | None = None
    meal_plan: str | None = None
    occupancy: int | None = None
    season_name: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    currency: str | None = None
    rate_per_night: Decimal | None = None
    confidence: float = 0.0
    source_note: str = ""
    page: int | None = None
    warnings: tuple[str, ...] = ()

    @property
    def is_complete(self) -> bool:
        return all(
            (
                self.room_type,
                self.meal_plan,
                self.occupancy,
                self.effective_from,
                self.effective_to,
                self.currency,
                self.rate_per_night is not None,
            )
        )


@dataclass
class ExtractionResult:

    rows: list[ExtractedRateRow] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    page_count: int = 0
    provider: str = ""

    @property
    def needs_other_provider(self) -> bool:
        return not self.rows and any("no text layer" in w for w in self.warnings)


class RateExtractionProvider(Protocol):

    name: str

    def supports(self, content_type: str, filename: str) -> bool: ...

    def extract(self, path: str, hint: ExtractionHint) -> ExtractionResult: ...
