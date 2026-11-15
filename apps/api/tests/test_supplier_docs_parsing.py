from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.supplier_docs.parsing import (
    parse_currency,
    parse_date_range,
    parse_meal_plan,
    parse_money,
    parse_occupancy,
    parse_season,
)

D = Decimal


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("23.920 KES", D("23920")),
        ("48.880 KES", D("48880")),
        ("21.840 KES", D("21840")),
        ("21,600", D("21600")),
        ("28,400", D("28400")),
        ("280", D("280")),
        ("1040", D("1040")),
        ("1.50", D("1.50")),
        ("129.50", D("129.50")),
    ],
)
def test_money_survives_every_separator_convention(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "-",
        "free of charge",
        "n/a",
        "280 370 500",
        "0",
    ],
)
def test_money_refuses_rather_than_guesses(text):
    assert parse_money(text) is None


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("04/01/2026 - 02/04/2026", date(2026, 1, 4), date(2026, 4, 2)),
        ("01/10/2026 - 30/10/2026", date(2026, 10, 1), date(2026, 10, 30)),
        ("11.01.27 - 19.12.27", date(2027, 1, 11), date(2027, 12, 19)),
        ("20.12.27 - 10.01.28", date(2027, 12, 20), date(2028, 1, 10)),
        ("21/12/2026-03/01/2027", date(2026, 12, 21), date(2027, 1, 3)),
        ("23 Dec - 3 Jan '27", date(2026, 12, 23), date(2027, 1, 3)),
    ],
)
def test_date_ranges_from_the_corpus(text, start, end):
    assert parse_date_range(text) == (start, end)


@pytest.mark.parametrize(
    ("text", "year", "start", "end"),
    [
        ("03 Jan - 02 Apr", 2026, date(2026, 1, 3), date(2026, 4, 2)),
        ("01 Nov - 30 Nov", 2026, date(2026, 11, 1), date(2026, 11, 30)),
        ("23 Dec - 3 Jan", 2026, date(2026, 12, 23), date(2027, 1, 3)),
    ],
)
def test_year_comes_from_the_document_when_the_row_omits_it(text, year, start, end):
    assert parse_date_range(text, default_year=year) == (start, end)


def test_a_price_is_never_read_as_a_year():
    assert parse_date_range("03 Jan - 02 Apr 280 370 500") == (None, None)
    start, end = parse_date_range("03 Jan - 02 Apr 280 370 500", default_year=2026)
    assert (start, end) == (date(2026, 1, 3), date(2026, 4, 2))


def test_the_real_typo_in_the_palmyra_shore_sheet_is_refused():
    assert parse_date_range("03/04-2026 - 06/04/2026") == (None, None)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("BB", "BB"),
        ("B&B", "BB"),
        ("Bed & Breakfast", "BB"),
        ("HB", "HB"),
        ("Half Board", "HB"),
        ("FB", "FB"),
        ("Full Board", "FB"),
        ("meal FB", "FB"),
        ("BO", "RO"),
        ("Room Only", "RO"),
        ("AI", "AI"),
    ],
)
def test_meal_plan_codes_map_onto_seeded_plans(text, code):
    assert parse_meal_plan(text) == code


@pytest.mark.parametrize(
    ("text", "occupancy"),
    [
        ("Single", 1),
        ("SGL", 1),
        ("Double", 2),
        ("Twin", 2),
        ("Double/Twin", 2),
        ("Triple", 3),
    ],
)
def test_occupancy_from_column_headings(text, occupancy):
    assert parse_occupancy(text) == occupancy


@pytest.mark.parametrize("text", ["SGL OR DBL", "room", "", None, "Standard Room"])
def test_ambiguous_occupancy_is_left_for_the_reviewer(text):
    assert parse_occupancy(text) is None


@pytest.mark.parametrize(
    ("text", "season"),
    [
        ("HIGH", "High"),
        ("LOW", "Low"),
        ("SHOULDER", "Shoulder"),
        ("PEAK", "Peak"),
        ("EASTER", "Easter"),
        ("FESTIVE SEASON", "Festive"),
    ],
)
def test_seasons_keep_the_sheets_own_vocabulary(text, season):
    assert parse_season(text) == season


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("23.920 KES", "KES"),
        ("KSH STO Rates", "KES"),
        ("USD 370", "USD"),
        ("$40 one-way", "USD"),
    ],
)
def test_currency_when_stated_unambiguously(text, code):
    assert parse_currency(text) == code


def test_currency_is_none_when_a_document_names_two():
    assert parse_currency("rooms in KSH, transfers in USD") is None
    assert parse_currency("no currency here") is None


def test_a_shared_price_heading_blocks_an_invented_occupancy():
    from app.modules.supplier_docs.extraction import _ambiguous_columns

    assert _ambiguous_columns(["", "SGL OR DBL", "Triple"], 3) == {1}
    assert _ambiguous_columns(["SGL", "OR", "DBL"], 3) == {0, 2}
    assert _ambiguous_columns(["Single", "Double", "Triple"], 3) == set()
    assert _ambiguous_columns(["Standard Room", "", "Superior Room"], 3) == set()


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("6th January - 28th February", date(2026, 1, 6), date(2026, 2, 28)),
        ("3rd April - 6th April", date(2026, 4, 3), date(2026, 4, 6)),
        ("1st March - 2nd April", date(2026, 3, 1), date(2026, 4, 2)),
        ("4 Jan - 30 April 26", date(2026, 1, 4), date(2026, 4, 30)),
        ("1 May - 20 July 26", date(2026, 5, 1), date(2026, 7, 20)),
    ],
)
def test_ordinal_and_bare_year_date_forms(text, start, end):
    assert parse_date_range(text, default_year=2026) == (start, end)


def test_the_document_year_is_the_commonest_not_the_earliest():
    from app.modules.supplier_docs.parsing import document_year

    assert document_year("MAY 2025 " + "2026 " * 6 + "2027 2027 2025") == 2026
    assert document_year("2027 2028") == 2027
    assert document_year("no years here") is None
    assert document_year("rate 2026 for 28,400") == 2026


def test_prose_season_definitions_are_collected_with_every_window():
    from app.modules.supplier_docs.parsing import season_windows

    text = (
        "SEASONS: DATES:\n"
        "High Season 6th January - 28th February; 3rd April - 6th April\n"
        "Green Season 1st March - 2nd April; 7th April - 31st July\n"
        "Peak Season 27th December 2026 - 5th January 2027\n"
    )
    found = season_windows(text, default_year=2026)
    assert found["High"] == [
        (date(2026, 1, 6), date(2026, 2, 28)),
        (date(2026, 4, 3), date(2026, 4, 6)),
    ]
    assert len(found["Green"]) == 2
    assert found["Peak"] == [(date(2026, 12, 27), date(2027, 1, 5))]


def test_a_fragmented_line_is_skipped_rather_than_misread():
    from app.modules.supplier_docs.blocks import _is_fragmented

    fragmented = [{"text": c} for c in "14,500"] + [{"text": x} for x in ("1", "4")]
    assert _is_fragmented(fragmented) is True
    intact = [{"text": t} for t in ("Club", "13,500", "13,100", "11,000", "10,600", "9,900")]
    assert _is_fragmented(intact) is False
    assert _is_fragmented([{"text": "a"}, {"text": "b"}]) is False
