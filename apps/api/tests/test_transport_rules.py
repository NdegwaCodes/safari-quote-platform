from __future__ import annotations

import pytest

from app.modules.quotes import transport as T

WHERE = "diani"


def _rail(sequence: int = 1, **kw) -> T.Segment:
    kw.setdefault("destination", WHERE)
    return T.Segment(sequence=sequence, kind=T.LINE_HAUL, mode="rail", **kw)


def _transfer(sequence: int, **kw) -> T.Segment:
    kw.setdefault("destination", WHERE)
    return T.Segment(sequence=sequence, kind=T.TRANSFER, mode="road", **kw)


def _codes(problems) -> set[str]:
    return {p.code for p in problems}


@pytest.mark.parametrize("legs,expected", [(1, 2), (2, 3), (3, 4), (0, 1)])
def test_a_journey_is_one_movement_per_transition_plus_both_ends(legs, expected):
    assert T.movements_needed(legs) == expected


def test_a_single_property_trip_still_needs_two_movements():
    assert T.movements_needed(1) == 2


def test_a_movement_without_a_destination_blocks():
    problems = T.check([_transfer(1, destination=None)], legs=1)
    fault = next(p for p in problems if p.code == T.NO_DESTINATION)
    assert fault.blocking is True
    assert fault.sequence == 1


def test_a_hired_vehicle_needs_no_destination():
    problems = T.check(
        [
            T.Segment(
                sequence=1, kind=T.LINE_HAUL, mode="road", has_vehicle=True
            )
        ],
        legs=1,
    )
    assert T.NO_DESTINATION not in _codes(problems)


def test_a_flight_needs_no_destination_because_it_is_never_priced():
    problems = T.check(
        [T.Segment(sequence=1, kind=T.LINE_HAUL, mode="air"), _transfer(2), _transfer(3)],
        legs=1,
    )
    assert T.NO_DESTINATION not in _codes(problems)


def test_a_flight_is_never_priceable():
    flight = T.Segment(sequence=1, kind=T.LINE_HAUL, mode="air")
    road = _transfer(2)
    assert T.priceable([flight, road]) == [road]
    assert T.named_only([flight, road]) == [flight]


def test_a_flight_is_reported_so_it_reaches_the_exclusions_and_does_not_block():
    problems = T.check(
        [T.Segment(sequence=1, kind=T.LINE_HAUL, mode="air"), _transfer(2), _transfer(3)],
        legs=1,
    )
    flight = [p for p in problems if p.code == T.FLIGHT_NAMED]
    assert len(flight) == 1
    assert flight[0].blocking is False
    assert "exclusion" in flight[0].message
    assert flight[0].sequence == 1


def test_air_is_not_an_unknown_mode_it_is_a_named_one():
    problems = T.check([T.Segment(sequence=1, kind=T.LINE_HAUL, mode="air")], legs=1)
    assert T.UNKNOWN_MODE not in _codes(problems)


def test_an_unsellable_mode_blocks():
    problems = T.check([T.Segment(sequence=1, kind=T.LINE_HAUL, mode="boat")], legs=1)
    fault = next(p for p in problems if p.code == T.UNKNOWN_MODE)
    assert fault.blocking is True


def test_an_unknown_kind_blocks():
    problems = T.check([T.Segment(sequence=1, kind="cruise", mode="road")], legs=1)
    fault = next(p for p in problems if p.code == T.UNKNOWN_KIND)
    assert fault.blocking is True


def test_rail_without_transfers_blocks():
    problems = T.check([_rail()], legs=1)
    fault = next(p for p in problems if p.code == T.RAIL_WITHOUT_TRANSFERS)
    assert fault.blocking is True
    assert "2 transfer legs" in fault.message


def test_one_rail_leg_needs_two_transfers():
    ok = T.check([_rail(1), _transfer(2), _transfer(3)], legs=1)
    assert T.RAIL_WITHOUT_TRANSFERS not in _codes(ok)
    short = T.check([_rail(1), _transfer(2)], legs=1)
    assert T.RAIL_WITHOUT_TRANSFERS in _codes(short)


def test_a_rail_return_needs_four_transfers():
    three = T.check([_rail(1), _rail(2), _transfer(3), _transfer(4), _transfer(5)], legs=1)
    assert T.RAIL_WITHOUT_TRANSFERS in _codes(three)
    four = T.check(
        [_rail(1), _rail(2), _transfer(3), _transfer(4), _transfer(5), _transfer(6)],
        legs=1,
    )
    assert T.RAIL_WITHOUT_TRANSFERS not in _codes(four)


def test_a_road_only_quote_needs_no_transfer_pairs():
    problems = T.check(
        [T.Segment(sequence=1, kind=T.LINE_HAUL, mode="road", has_vehicle=True)],
        legs=1,
    )
    assert T.RAIL_WITHOUT_TRANSFERS not in _codes(problems)


def test_an_optional_transfer_still_counts_toward_the_rail_requirement():
    problems = T.check(
        [_rail(1), _transfer(2), _transfer(3, is_optional=True)], legs=1
    )
    assert T.RAIL_WITHOUT_TRANSFERS not in _codes(problems)


def test_a_two_destination_package_with_one_transfer_is_short():
    problems = T.check([_transfer(1)], legs=2)
    fault = next(p for p in problems if p.code == T.MISSING_MOVEMENTS)
    assert fault.blocking is False
    assert "takes 3 movements" in fault.message
    assert "prices 1" in fault.message


def test_full_coverage_is_silent():
    problems = T.check([_transfer(1), _transfer(2), _transfer(3)], legs=2)
    assert T.MISSING_MOVEMENTS not in _codes(problems)


def test_a_hired_vehicle_covers_every_movement_at_once():
    problems = T.check(
        [T.Segment(sequence=1, kind=T.LINE_HAUL, mode="road", has_vehicle=True)],
        legs=3,
    )
    assert T.MISSING_MOVEMENTS not in _codes(problems)


def test_an_optional_extra_does_not_cover_a_required_movement():
    problems = T.check([_transfer(1), _transfer(2, is_optional=True)], legs=1)
    assert T.MISSING_MOVEMENTS in _codes(problems)


def test_shortfall_is_advice_not_a_refusal():
    problems = T.check([_transfer(1)], legs=1)
    assert all(p.blocking is False for p in problems)


def test_no_segments_is_reported_once_and_does_not_block():
    problems = T.check([], legs=2)
    assert [p.code for p in problems] == [T.NO_SEGMENTS]
    assert problems[0].blocking is False


def test_vvip_inside_the_package_price_is_flagged():
    problems = T.check([_transfer(1, is_vvip=True), _transfer(2)], legs=1)
    fault = next(p for p in problems if p.code == T.VVIP_NOT_OPTIONAL)
    assert fault.blocking is False
    assert fault.sequence == 1


def test_vvip_as_an_add_on_is_silent_and_priced_separately():
    segments = [_transfer(1), _transfer(2), _transfer(3, is_vvip=True, is_optional=True)]
    problems = T.check(segments, legs=1)
    assert T.VVIP_NOT_OPTIONAL not in _codes(problems)
    assert [s.sequence for s in T.optional_extras(segments)] == [3]
    assert [s.sequence for s in T.priceable(segments)] == [1, 2]


@pytest.mark.parametrize(
    "tariff,basis",
    [("per_person", "per_person"), ("per_vehicle", "per_group"), ("per_leg", "per_group")],
)
def test_a_tariff_basis_maps_onto_a_cost_line_basis(tariff, basis):
    assert T.line_basis(tariff) == basis


def test_an_unknown_basis_raises_rather_than_guessing():
    with pytest.raises(ValueError, match="unknown transport cost basis"):
        T.line_basis("per_kilometre")


def test_every_declared_cost_basis_has_a_mapping():
    from app.modules.transport.models import COST_BASES

    for basis in COST_BASES:
        assert T.line_basis(basis)


def test_the_modes_we_price_are_the_modes_the_model_offers():
    from app.modules.transport.models import TRANSPORT_MODES

    assert set(T.PRICED_MODES) == set(TRANSPORT_MODES)
    assert "air" not in TRANSPORT_MODES


def test_segments_are_read_in_the_order_they_were_typed():
    out = T.priceable([_transfer(3), _transfer(1), _transfer(2)])
    assert [s.sequence for s in out] == [1, 2, 3]
