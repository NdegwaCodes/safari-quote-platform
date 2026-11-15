from __future__ import annotations

from dataclasses import replace

import pdfplumber

from app.core.storage import resolve
from app.integrations.rate_extraction import (
    ExtractionHint,
    ExtractionResult,
    RateExtractionProvider,
)
from app.modules.supplier_docs.blocks import BlockRateExtractor
from app.modules.supplier_docs.extraction import GridRateExtractor
from app.modules.supplier_docs.parsing import document_year, season_windows


def _score(result: ExtractionResult) -> tuple[int, int]:
    complete = sum(1 for row in result.rows if row.is_complete)
    return complete, len(result.rows)


class CompositeRateExtractor:
    name = "pdf-composite"

    def __init__(self, providers: list[RateExtractionProvider] | None = None) -> None:
        self.providers: list[RateExtractionProvider] = providers or [
            GridRateExtractor(),
            BlockRateExtractor(),
        ]

    def supports(self, content_type: str, filename: str) -> bool:
        return any(p.supports(content_type, filename) for p in self.providers)

    def extract(self, path: str, hint: ExtractionHint) -> ExtractionResult:
        attempts: list[ExtractionResult] = [
            provider.extract(path, hint)
            for provider in self.providers
            if provider.supports("application/pdf", path)
        ]
        if not attempts:
            return ExtractionResult(
                warnings=["no extraction provider can read this file"],
                provider=self.name,
            )

        best = max(attempts, key=_score)
        if _score(best) == (0, 0):
            merged = ExtractionResult(provider=self.name, page_count=best.page_count)
            for attempt in attempts:
                merged.warnings.extend(
                    f"[{attempt.provider}] {warning}" for warning in attempt.warnings
                )
            if not merged.warnings:
                merged.warnings.append(
                    "no rates were recognised in this document; enter them by hand "
                    "against the stored file"
                )
            return merged

        best.provider = f"{self.name}:{best.provider}"
        self._date_undated_seasons(best, path)
        return best

    @staticmethod
    def _date_undated_seasons(result: ExtractionResult, path: str) -> None:
        undated = [
            row
            for row in result.rows
            if row.season_name and not (row.effective_from and row.effective_to)
        ]
        if not undated:
            return

        try:
            with pdfplumber.open(resolve(path)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:  # noqa: BLE001 - the rows are already usable without this
            return

        windows = season_windows(text, default_year=document_year(text))
        if not windows:
            return

        for index, row in enumerate(result.rows):
            if row not in undated or row.season_name is None:
                continue
            found = windows.get(row.season_name)
            if not found:
                continue
            if len(found) > 1:
                result.rows[index] = replace(
                    row,
                    warnings=(
                        *row.warnings,
                        f"the sheet gives {len(found)} separate windows for the "
                        f"{row.season_name} season, so which one this rate belongs "
                        f"to has to be chosen by hand",
                    ),
                )
                continue
            start, end = found[0]
            result.rows[index] = replace(
                row,
                effective_from=start,
                effective_to=end,
                warnings=tuple(
                    w
                    for w in row.warnings
                    if "season window" not in w and "date window" not in w
                ),
                source_note=(
                    f"{row.source_note} (dates from the sheet's "
                    f"{row.season_name} season definition)"
                )[:500],
            )
