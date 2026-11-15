from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.public.estimate import (
    NO_TIER,
    ROOM_CAPACITY,
    Combined,
    EstimateRefused,
    LegPriced,
    combine,
    price_rooms,
    star_band,
)

D = Decimal


def test_an_unknown_tier_is_refused_by_name():
    with pytest.raises(EstimateRefused) as raised:
        star_band("premium")
    assert raised.value.code == NO_TIER
    assert "comfort, luxury or ultra" in raised.value.message


def test_the_three_tiers_are_disjoint_star_bands():
    assert star_band("comfort") == (1, 3)
    assert star_band("luxury") == (4, 4)
    assert star_band("ultra") == (5, 5)


def test_two_sharing_pays_the_double_rate():
    rates = {1: D("100"), 2: D("160")}
    assert price_rooms(rates, pax=2) == D("160")


def test_a_lone_guest_pays_the_filed_double_because_there_is_no_single():
    rates = {2: D("160")}
    assert price_rooms(rates, pax=1) == D("160")


def test_an_uneven_party_prices_a_full_room_and_a_part_room():
    rates = {2: D("160")}
    assert price_rooms(rates, pax=3) == D("320")


def test_a_property_with_nothing_filed_for_any_usable_occupancy_is_none():
    assert price_rooms({}, pax=2) is None


def test_room_capacity_is_two():
    assert ROOM_CAPACITY == 2


def _leg(**over):
    fields = {
        "destination": "Diani",
        "tier": "luxury",
        "nights": 3,
        "property_name": "Reef House",
        "room_type": "Garden Twin",
        "meal_plan": "BB",
        "currency": "KES",
        "per_person": D("45000"),
        "group_total": D("90000"),
        "refused": None,
    }
    fields.update(over)
    return LegPriced(**fields)


def test_one_currency_throughout_sums_to_a_trip_total():
    second = _leg(destination="Watamu", per_person=D("30000"), group_total=D("60000"))
    found = combine([_leg(), second])
    assert found == Combined(currency="KES", per_person=D("75000"), group_total=D("150000"))


def test_mixed_currencies_refuse_to_be_summed():
    found = combine([_leg(currency="KES"), _leg(destination="Laikipia", currency="USD")])
    assert found.currency is None
    assert found.per_person is None
    assert found.group_total is None
    assert found.mixed_currency is True


def test_any_refused_leg_means_no_trip_total_either():
    refused = LegPriced(
        destination="Mara", tier="ultra", nights=4,
        refused=EstimateRefused("estimate_no_property", "no ultra property yet"),
    )
    found = combine([_leg(), refused])
    assert found.currency is None
    assert found.mixed_currency is False


def test_a_single_leg_trip_combines_trivially():
    found = combine([_leg()])
    assert found.currency == "KES"
    assert found.per_person == D("45000")
