from __future__ import annotations

from decimal import Decimal
from itertools import product

import pytest

from app.modules.quotes.cohorts import (
    BASES,
    Cohort,
    CostLine,
    Group,
    attribute,
    group_from_counts,
    multiplier,
    price_group,
)

D = Decimal

KES = "KES"
USD = "USD"
CURRENCIES = {"citizen": KES, "non_resident": USD}
CONTRACT_RATE = D("130")


def _convert(amount: Decimal, source: str, target: str) -> Decimal:
    if source == target:
        return amount
    if (source, target) == (USD, KES):
        return amount * CONTRACT_RATE
    if (source, target) == (KES, USD):
        return amount / CONTRACT_RATE
    raise AssertionError(f"no test rate for {source}->{target}")


def _rate(source: str, target: str) -> Decimal:
    return D(1) if source == target else CONTRACT_RATE


def _group(*counts: tuple[str, str, int]) -> Group:
    return group_from_counts(counts, CURRENCIES)


def _all_resident(pax: int) -> Group:
    return _group(("citizen", "adult", pax))


def test_every_basis_has_a_multiplier():
    for basis in BASES:
        assert (
            multiplier(basis, pax=10, nights=3, days=3, rooms=5) >= 1
        ), basis


def test_the_basis_changes_the_answer_completely():
    args = {"pax": 25, "nights": 3, "days": 3, "rooms": 13}
    assert multiplier("per_person_per_night", **args) == 75
    assert multiplier("per_person", **args) == 25
    assert multiplier("per_room_per_night", **args) == 39
    assert multiplier("per_room", **args) == 13
    assert multiplier("per_group_per_night", **args) == 3
    assert multiplier("per_group", **args) == 1


def test_nights_and_days_are_not_the_same_count():
    day_trip = {"pax": 4, "nights": 0, "days": 1, "rooms": 0}
    assert multiplier("per_person_per_day", **day_trip) == 4
    assert multiplier("per_person_per_night", **day_trip) == 0


def test_units_scale_a_basis():
    assert multiplier("per_group", pax=25, nights=3, days=3, rooms=13, units=2) == 2


def test_an_unknown_basis_is_refused_rather_than_assumed():
    with pytest.raises(ValueError, match="unknown cost basis"):
        multiplier("per_fortnight", pax=1, nights=1, days=1, rooms=1)


def test_a_headcount_is_the_sum_of_its_cohorts():
    group = _group(
        ("citizen", "adult", 18),
        ("citizen", "child", 2),
        ("non_resident", "adult", 5),
    )
    assert group.pax == 25
    assert group.headcount("citizen") == 20
    assert group.headcount("non_resident") == 5


def test_empty_boxes_on_a_form_are_not_an_error():
    group = _group(
        ("citizen", "adult", 4),
        ("citizen", "child", 0),
        ("citizen", "infant", 0),
    )
    assert group.pax == 4
    assert len(group.cohorts) == 1


def test_a_group_with_nobody_in_it_is_refused():
    with pytest.raises(ValueError, match="at least one traveller"):
        _group(("citizen", "adult", 0))


def test_the_same_cohort_twice_is_refused():
    with pytest.raises(ValueError, match="duplicate cohort"):
        Group(
            cohorts=(
                Cohort("citizen", "adult", 5, KES),
                Cohort("citizen", "adult", 3, KES),
            )
        )


def test_one_residency_cannot_be_billed_in_two_currencies():
    with pytest.raises(ValueError, match="disagree on currency"):
        Group(
            cohorts=(
                Cohort("citizen", "adult", 5, KES),
                Cohort("citizen", "child", 2, USD),
            )
        )


def test_a_single_cohort_group_is_uniform():
    assert _all_resident(25).is_uniform is True
    assert _group(("citizen", "adult", 24), ("citizen", "child", 1)).is_uniform is False


def test_children_share_their_parents_room():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 2))
    assert group.rooming(capacity=4) == {"citizen": [4]}
    assert group.total_rooms(capacity=4) == 1


def test_a_family_in_twins_is_two_rooms_not_four():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 2))
    assert group.total_rooms(capacity=2) == 2


def test_residencies_are_roomed_separately():
    group = _group(("citizen", "adult", 3), ("non_resident", "adult", 3))
    assert group.rooming(capacity=2) == {"citizen": [2, 1], "non_resident": [2, 1]}
    assert group.total_rooms(capacity=2) == 4


def test_the_extra_room_is_the_price_of_mixed_residency():
    mixed = _group(("citizen", "adult", 3), ("non_resident", "adult", 3))
    single = _all_resident(6)
    assert mixed.total_rooms(capacity=2) == 4
    assert single.total_rooms(capacity=2) == 3


@pytest.mark.parametrize(
    "residents,non_residents",
    [(a, b) for a, b in product(range(0, 21), range(0, 21)) if a + b > 0],
)
def test_everyone_gets_a_bed_whatever_the_split(residents, non_residents):
    counts = []
    if residents:
        counts.append(("citizen", "adult", residents))
    if non_residents:
        counts.append(("non_resident", "adult", non_residents))
    group = group_from_counts(counts, CURRENCIES)
    plan = group.rooming(capacity=2)
    assert sum(sum(rooms) for rooms in plan.values()) == group.pax
    assert all(0 < occupants <= 2 for rooms in plan.values() for occupants in rooms)
    whole = -(-group.pax // 2)
    assert whole <= group.total_rooms(capacity=2) <= whole + len(group.residences)


def test_twenty_five_residents_is_still_thirteen_rooms():
    assert _all_resident(25).total_rooms(capacity=2) == 13
    assert _all_resident(7).total_rooms(capacity=2) == 4


def test_a_shared_cost_is_split_per_head():
    group = _group(("citizen", "adult", 15), ("non_resident", "adult", 0))
    lines = [CostLine("coach", D("100000"), KES, "per_group")]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:adult"]["coach"] == D("100000")


def test_a_shared_cost_across_cohorts_sums_exactly():
    group = _group(("citizen", "adult", 3), ("citizen", "child", 4))
    attributed = attribute(
        [CostLine("chef", D("100000"), KES, "per_group")], group, capacity=2
    )
    total = sum(bucket["chef"] for bucket in attributed.values())
    assert total == D("100000")


def test_a_residence_scoped_line_reaches_only_that_residency():
    group = _group(("citizen", "adult", 10), ("non_resident", "adult", 5))
    lines = [
        CostLine("accommodation", D("343500"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("2400"), USD, "per_group", residence="non_resident"),
    ]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:adult"]["accommodation"] == D("343500")
    assert attributed["non_resident:adult"]["accommodation"] == D("2400")


def test_a_child_line_reaches_only_the_children():
    group = _group(("citizen", "adult", 10), ("citizen", "child", 4))
    lines = [
        CostLine(
            "park fees", D("500"), KES, "per_person_per_day",
            residence="citizen", traveller_type="child", days=3,
        ),
        CostLine(
            "park fees", D("1000"), KES, "per_person_per_day",
            residence="citizen", traveller_type="adult", days=3,
        ),
    ]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:child"]["park fees"] == D("6000")
    assert attributed["citizen:adult"]["park fees"] == D("30000")


def test_a_child_rate_on_an_all_adult_group_is_dropped_not_reassigned():
    group = _all_resident(10)
    lines = [
        CostLine(
            "child fee", D("500"), KES, "per_person",
            residence="citizen", traveller_type="child",
        )
    ]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:adult"] == {}


def test_a_line_in_the_wrong_currency_with_no_converter_is_refused():
    group = _all_resident(10)
    lines = [CostLine("boat", D("400"), USD, "per_group")]
    with pytest.raises(ValueError, match="no converter was given"):
        attribute(lines, group, capacity=2)


def test_a_shared_cost_on_a_mixed_currency_group_converts_per_share():
    group = _group(("citizen", "adult", 10), ("non_resident", "adult", 3))
    lines = [CostLine("coach", D("65000"), KES, "per_group")]
    attributed = attribute(lines, group, capacity=2, convert=_convert)
    assert attributed["citizen:adult"]["coach"] == D("50000")
    non_resident = attributed["non_resident:adult"]["coach"]
    assert non_resident == D("15000") / CONTRACT_RATE


def test_a_converted_share_round_trips_to_the_original_total():
    group = _group(("citizen", "adult", 10), ("non_resident", "adult", 3))
    attributed = attribute(
        [CostLine("coach", D("65000"), KES, "per_group")],
        group, capacity=2, convert=_convert,
    )
    back = (
        attributed["citizen:adult"]["coach"]
        + attributed["non_resident:adult"]["coach"] * CONTRACT_RATE
    )
    assert abs(back - D("65000")) < D("0.01")


def test_the_share_is_split_before_it_is_converted():
    group = _group(("citizen", "adult", 1), ("non_resident", "adult", 2))
    attributed = attribute(
        [CostLine("boat", D("300"), KES, "per_group")],
        group, capacity=2, convert=_convert,
    )
    assert attributed["citizen:adult"]["boat"] == D("100")
    assert attributed["non_resident:adult"]["boat"] == D("200") / CONTRACT_RATE


def test_a_traveller_type_without_a_residence_is_not_expressible():
    with pytest.raises(ValueError, match="names a traveller type without a residence"):
        CostLine("all children", D("500"), KES, "per_person", traveller_type="child")


def test_a_negative_cost_line_is_refused():
    with pytest.raises(ValueError, match="negative"):
        CostLine("discount", D("-500"), KES, "per_group")


def test_room_based_lines_use_that_residency_rooms():
    group = _group(("citizen", "adult", 3), ("non_resident", "adult", 3))
    lines = [
        CostLine(
            "levy", D("200"), KES, "per_room_per_night",
            residence="citizen", nights=2,
        )
    ]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:adult"]["levy"] == D("800")


def test_two_lines_with_one_label_accumulate():
    group = _all_resident(10)
    lines = [
        CostLine("park fees", D("1000"), KES, "per_person", residence="citizen"),
        CostLine("park fees", D("500"), KES, "per_person", residence="citizen"),
    ]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:adult"]["park fees"] == D("15000")


def _price(group, lines, **over):
    kwargs = {
        "lines": lines,
        "group": group,
        "capacity": 2,
        "contingency_pct": D("5"),
        "profit_pct": D("24"),
        "group_currency": KES,
        "convert": _convert,
        "rate_used": _rate,
    }
    kwargs.update(over)
    return price_group(**kwargs)


def test_a_single_residency_group_prices_exactly_as_before():
    group = _all_resident(25)
    lines = [
        CostLine("accommodation", D("343500"), KES, "per_group", residence="citizen")
    ]
    priced = _price(group, lines)
    assert len(priced.cohorts) == 1
    assert priced.per_person("citizen") == D("17900")
    assert priced.group_total == D("447500")


def test_each_cohort_gets_its_own_per_person_figure():
    group = _group(("citizen", "adult", 20), ("non_resident", "adult", 5))
    lines = [
        CostLine("accommodation", D("270000"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("1620"), USD, "per_group", residence="non_resident"),
    ]
    priced = _price(group, lines)
    assert priced.per_person("citizen") == D("17600")
    assert priced.per_person("non_resident") == D("500")
    assert priced.group_total == D("352000") + D("325000")


def test_the_conversion_rate_is_disclosed():
    group = _group(("citizen", "adult", 10), ("non_resident", "adult", 2))
    lines = [
        CostLine("accommodation", D("90000"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("700"), USD, "per_group", residence="non_resident"),
    ]
    priced = _price(group, lines)
    assert priced.conversions == {"USD/KES": CONTRACT_RATE}


def test_a_single_currency_group_needs_no_converter():
    group = _all_resident(10)
    lines = [CostLine("accommodation", D("90000"), KES, "per_group", residence="citizen")]
    priced = _price(group, lines, convert=None, rate_used=None)
    assert priced.group_total > 0
    assert priced.conversions == {}


def test_a_missing_converter_is_an_error_not_a_silent_omission():
    group = _group(("citizen", "adult", 10), ("non_resident", "adult", 2))
    lines = [
        CostLine("accommodation", D("90000"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("700"), USD, "per_group", residence="non_resident"),
    ]
    with pytest.raises(ValueError, match="no converter"):
        _price(group, lines, convert=None)


@pytest.mark.parametrize(
    "composition",
    [
        (("citizen", "adult", 25),),
        (("citizen", "adult", 24), ("citizen", "child", 1)),
        (("citizen", "adult", 20), ("non_resident", "adult", 5)),
        (("citizen", "adult", 12), ("citizen", "child", 3), ("non_resident", "adult", 10)),
        (("non_resident", "adult", 2), ("non_resident", "infant", 1)),
        (("citizen", "adult", 1),),
    ],
)
def test_every_cohort_reconciles_with_its_own_total(composition):
    group = group_from_counts(composition, CURRENCIES)
    lines = [
        CostLine("accommodation", D("400000"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("3000"), USD, "per_group", residence="non_resident"),
    ]
    if len(group.residences) == 1:
        currency = group.currency_for(group.residences[0])
        lines.append(
            CostLine(
                "boat", D("60000") if currency == KES else D("500"),
                currency, "per_group",
            )
        )
    priced = _price(group, lines)
    for price in priced.cohorts:
        assert price.per_person * price.cohort.count == price.total, price.cohort.key


@pytest.mark.parametrize(
    "composition",
    [
        (("citizen", "adult", 25),),
        (("citizen", "adult", 24), ("citizen", "child", 1)),
        (("citizen", "adult", 10), ("citizen", "child", 5), ("citizen", "infant", 2)),
    ],
)
def test_the_group_total_is_the_sum_of_the_cohort_totals(composition):
    group = group_from_counts(composition, CURRENCIES)
    lines = [
        CostLine("accommodation", D("343500"), KES, "per_group", residence="citizen"),
        CostLine("chef", D("30000"), KES, "per_group"),
    ]
    priced = _price(group, lines)
    assert priced.group_total == sum(price.total for price in priced.cohorts)


def test_the_group_total_never_undercharges_after_rounding():
    group = _group(("citizen", "adult", 7), ("citizen", "child", 3))
    lines = [
        CostLine("accommodation", D("123456"), KES, "per_group", residence="citizen")
    ]
    priced = _price(group, lines)
    raw = sum(price.build_up.selling_total for price in priced.cohorts)
    assert priced.group_total >= raw
    assert priced.group_total - raw < D("100") * group.pax


def test_the_agent_cover_fee_is_split_per_head_and_never_marked_up():
    group = _group(("citizen", "adult", 20), ("non_resident", "adult", 5))
    lines = [
        CostLine("accommodation", D("270000"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("1620"), USD, "per_group", residence="non_resident"),
    ]
    with_fee = _price(group, lines, agent_cover_fee=D("25000"))
    shares = {
        price.cohort.key: price.build_up.agent_cover_fee
        for price in with_fee.cohorts
    }
    assert shares["citizen:adult"] == D("20000")
    assert shares["non_resident:adult"] == D("5000")
    assert sum(shares.values()) == D("25000")
    for price in with_fee.cohorts:
        assert (
            price.build_up.after_profit + price.build_up.agent_cover_fee
            == price.build_up.selling_total
        )


def test_a_child_priced_at_a_child_rate_pays_less_than_an_adult():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 2))
    lines = [
        CostLine("accommodation", D("48000"), KES, "per_group", residence="citizen"),
        CostLine(
            "park fees", D("1000"), KES, "per_person_per_day",
            residence="citizen", traveller_type="adult", days=3,
        ),
        CostLine(
            "park fees", D("500"), KES, "per_person_per_day",
            residence="citizen", traveller_type="child", days=3,
        ),
    ]
    priced = _price(group, lines, capacity=4)
    adult = priced.per_person("citizen", "adult")
    child = priced.per_person("citizen", "child")
    assert child < adult


def test_every_figure_stays_decimal():
    group = _group(("citizen", "adult", 3), ("non_resident", "adult", 2))
    lines = [
        CostLine("accommodation", D("33333"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("777"), USD, "per_group", residence="non_resident"),
    ]
    priced = _price(group, lines)
    assert isinstance(priced.group_total, Decimal)
    for price in priced.cohorts:
        assert isinstance(price.per_person, Decimal)
        assert isinstance(price.total, Decimal)


def test_attribution_loses_nothing():
    group = _group(
        ("citizen", "adult", 12),
        ("citizen", "child", 3),
        ("non_resident", "adult", 10),
    )
    lines = [
        CostLine("accommodation", D("400000"), KES, "per_group", residence="citizen"),
        CostLine("accommodation", D("3000"), USD, "per_group", residence="non_resident"),
        CostLine(
            "park fees", D("1000"), KES, "per_person_per_day",
            residence="citizen", traveller_type="adult", days=2,
        ),
    ]
    attributed = attribute(lines, group, capacity=2)
    kes = sum(
        amount
        for key, bucket in attributed.items()
        if key.startswith("citizen")
        for amount in bucket.values()
    )
    usd = sum(
        amount
        for key, bucket in attributed.items()
        if key.startswith("non_resident")
        for amount in bucket.values()
    )
    assert kes == D("400000") + D("24000")
    assert usd == D("3000")


def test_children_do_not_add_rooms_when_the_sheet_prices_them():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 2))
    assert group.rooming(2) == {"citizen": [2, 2]}
    assert group.rooming(2, occupants={"citizen": 2}) == {"citizen": [2]}


def test_a_residency_left_out_of_the_override_keeps_its_headcount():
    group = _group(
        ("citizen", "adult", 2),
        ("citizen", "child", 1),
        ("non_resident", "adult", 2),
        ("non_resident", "child", 1),
    )
    rooming = group.rooming(2, occupants={"citizen": 2})
    assert rooming == {"citizen": [2], "non_resident": [2, 1]}


def test_count_of_names_one_cohort():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 3))
    assert group.count_of("citizen", "child") == 3
    assert group.count_of("citizen", "infant") == 0
    assert group.count_of("non_resident", "adult") == 0


def test_a_room_line_reaches_only_the_travellers_it_was_priced_for():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 2))
    lines = [
        CostLine(
            "accommodation", D("60000"), KES, "per_group",
            residence="citizen", bearers=("adult", "infant"),
        ),
        CostLine(
            "accommodation", D("30000"), KES, "per_group",
            residence="citizen", traveller_type="child",
        ),
    ]
    attributed = attribute(lines, group, capacity=2)
    assert attributed["citizen:adult"] == {"accommodation": D("60000")}
    assert attributed["citizen:child"] == {"accommodation": D("30000")}


def test_bearers_and_a_traveller_type_on_one_line_is_refused():
    with pytest.raises(ValueError, match="either to one cohort or to several"):
        CostLine(
            "accommodation", D("1"), KES, "per_group",
            residence="citizen", traveller_type="child", bearers=("adult",),
        )


def test_bearers_without_a_residence_is_refused():
    with pytest.raises(ValueError, match="two sheets is not one line"):
        CostLine("accommodation", D("1"), KES, "per_group", bearers=("adult",))


def test_a_room_nobody_is_left_to_bear_is_an_error_not_a_silent_drop():
    children_only = _group(("citizen", "child", 2))
    with pytest.raises(ValueError, match="no citizen cohort is one of them"):
        attribute(
            [
                CostLine(
                    "accommodation", D("60000"), KES, "per_group",
                    residence="citizen", bearers=("adult", "infant"),
                )
            ],
            children_only,
            capacity=2,
        )


def test_the_cohort_totals_still_sum_to_the_group_total_with_a_child_bed():
    group = _group(("citizen", "adult", 2), ("citizen", "child", 2))
    priced = _price(
        group,
        [
            CostLine(
                "accommodation", D("60000"), KES, "per_group",
                residence="citizen", bearers=("adult", "infant"),
            ),
            CostLine(
                "accommodation", D("30000"), KES, "per_group",
                residence="citizen", traveller_type="child",
            ),
        ],
    )
    assert priced.group_total == sum(price.total for price in priced.cohorts)
    for price in priced.cohorts:
        assert price.total == price.per_person * price.cohort.count
    child = next(p for p in priced.cohorts if p.cohort.traveller_type == "child")
    adult = next(p for p in priced.cohorts if p.cohort.traveller_type == "adult")
    assert child.per_person < adult.per_person
