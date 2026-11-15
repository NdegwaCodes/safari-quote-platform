from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.quotes import packages as P
from app.modules.quotes.packages import Leg

ARRIVAL, DEPARTURE = date(2026, 7, 1), date(2026, 7, 8)


def leg(sequence, destination, check_in, check_out, name=""):
    return Leg(
        sequence=sequence,
        destination=destination,
        check_in=date(2026, 7, check_in),
        check_out=date(2026, 7, check_out),
        property_name=name,
    )


def valid():
    return [
        leg(1, "Nairobi", 1, 2, "Sorrel Hotel"),
        leg(2, "Maasai Mara", 2, 5, "Nyota Mara Camp"),
        leg(3, "Diani", 5, 8, "Palmyra Shore Resort"),
    ]


def codes(problems):
    return {problem.code for problem in problems}


def _check(legs, **over):
    kwargs = {"arrival": ARRIVAL, "departure": DEPARTURE}
    kwargs.update(over)
    return P.check(legs, **kwargs)


def test_a_contiguous_package_has_no_problems():
    assert _check(valid()) == []


def test_the_legs_nights_add_up_to_the_stay():
    legs = valid()
    assert [entry.nights for entry in P.order(legs)] == [1, 3, 3]
    assert P.total_nights(legs) == (DEPARTURE - ARRIVAL).days == 7


def test_check_out_is_the_next_leg_check_in():
    first, second, third = P.order(valid())
    assert first.check_out == second.check_in
    assert second.check_out == third.check_in


def test_a_legs_nights_exclude_its_check_out_date():
    nights = P.nights_of(leg(3, "Diani", 5, 8))
    assert nights == [date(2026, 7, 5), date(2026, 7, 6), date(2026, 7, 7)]
    assert date(2026, 7, 8) not in nights


def test_order_is_by_sequence_and_never_by_date():
    legs = valid()
    scrambled = [legs[2], legs[0], legs[1]]
    assert [entry.sequence for entry in P.order(scrambled)] == [1, 2, 3]

    wrong = [
        leg(1, "Diani", 5, 8),
        leg(2, "Nairobi", 1, 2),
        leg(3, "Maasai Mara", 2, 5),
    ]
    assert P.order(wrong)[0].destination == "Diani"
    assert codes(_check(wrong)) & {P.OVERLAP, P.EARLY_START, P.LONG_END}


def test_a_gap_between_legs_is_blocking():
    legs = [
        leg(1, "Nairobi", 1, 2),
        leg(2, "Maasai Mara", 3, 5),
        leg(3, "Diani", 5, 8),
    ]
    problems = _check(legs)
    assert P.GAP in codes(problems)
    assert P.blocking(problems)
    gap = next(p for p in problems if p.code == P.GAP)
    assert "1 night(s)" in gap.message
    assert gap.sequence == 2


def test_an_overlap_between_legs_is_blocking():
    legs = [
        leg(1, "Nairobi", 1, 3),
        leg(2, "Maasai Mara", 2, 5),
        leg(3, "Diani", 5, 8),
    ]
    problems = _check(legs)
    assert P.OVERLAP in codes(problems)
    overlap = next(p for p in problems if p.code == P.OVERLAP)
    assert "1 night(s)" in overlap.message


@pytest.mark.parametrize("size", [1, 2, 5])
def test_a_gap_reports_how_many_nights_are_missing(size):
    legs = [leg(1, "Nairobi", 1, 2), leg(2, "Diani", 2 + size, 8)]
    gap = next(p for p in _check(legs) if p.code == P.GAP)
    assert f"{size} night(s)" in gap.message


def test_a_leg_that_checks_out_before_it_checks_in_is_caught():
    legs = [leg(1, "Nairobi", 5, 2)]
    assert P.BAD_RANGE in codes(_check(legs))


def test_a_zero_night_leg_is_not_a_leg():
    legs = [leg(1, "Nairobi", 1, 1), leg(2, "Diani", 1, 8)]
    assert P.BAD_RANGE in codes(_check(legs))


def test_a_package_starting_after_arrival_is_blocking():
    legs = [leg(1, "Nairobi", 2, 3), leg(2, "Diani", 3, 8)]
    problems = _check(legs)
    assert P.LATE_START in codes(problems)
    assert "1 night(s) unaccounted" in next(
        p for p in problems if p.code == P.LATE_START
    ).message


def test_a_package_starting_before_arrival_is_blocking():
    legs = [leg(1, "Nairobi", 1, 2)]
    assert P.EARLY_START in codes(
        _check(legs, arrival=date(2026, 7, 2), departure=date(2026, 7, 2))
    )


def test_a_package_ending_before_departure_is_blocking():
    legs = [
        leg(1, "Nairobi", 1, 2),
        leg(2, "Maasai Mara", 2, 5),
        leg(3, "Diani", 5, 7),
    ]
    problems = _check(legs)
    assert P.SHORT_END in codes(problems)
    assert "1 night(s) unaccounted" in next(
        p for p in problems if p.code == P.SHORT_END
    ).message


def test_a_package_running_past_departure_is_blocking():
    legs = [leg(1, "Nairobi", 1, 2), leg(2, "Diani", 2, 9)]
    assert P.LONG_END in codes(_check(legs))


def test_an_empty_package_cannot_be_priced():
    problems = _check([])
    assert codes(problems) == {P.NO_LEGS}
    assert P.blocking(problems)


def test_a_leg_below_its_minimum_stay_blocks_the_whole_package():
    legs = valid()
    problems = _check(legs, minimum_stay={1: 2})
    assert P.TOO_SHORT in codes(problems)
    assert P.blocking(problems)
    assert "requires 2" in next(
        p for p in problems if p.code == P.TOO_SHORT
    ).message


def test_a_leg_meeting_its_minimum_stay_passes():
    assert _check(valid(), minimum_stay={2: 3, 3: 3}) == []


def test_a_minimum_stay_for_a_leg_that_does_not_exist_is_ignored():
    assert _check(valid(), minimum_stay={9: 40}) == []


def test_two_legs_at_one_position_leave_the_order_undefined():
    legs = [
        leg(1, "Nairobi", 1, 2),
        leg(1, "Maasai Mara", 2, 5),
        leg(3, "Diani", 5, 8),
    ]
    assert P.DUPLICATE_SEQUENCE in codes(_check(legs))


def test_a_repeated_destination_is_a_note_not_a_fault():
    legs = [
        leg(1, "Nairobi", 1, 2),
        leg(2, "Maasai Mara", 2, 7),
        leg(3, "Nairobi", 7, 8),
    ]
    problems = _check(legs)
    assert codes(problems) == {P.REPEATED_DESTINATION}
    assert P.blocking(problems) == []
    assert "check it is not a copied leg" in problems[0].message


@pytest.mark.parametrize("nights", [7, 14, 21, 30])
def test_a_trip_of_any_length_the_client_named_validates(nights):
    arrival = date(2026, 7, 1)
    departure = arrival + timedelta(days=nights)
    each = nights // 3
    first = arrival + timedelta(days=each)
    second = first + timedelta(days=each)
    legs = [
        Leg(1, "Nairobi", arrival, first),
        Leg(2, "Maasai Mara", first, second),
        Leg(3, "Diani", second, departure),
    ]
    assert P.check(legs, arrival=arrival, departure=departure) == []
    assert P.total_nights(legs) == nights


def test_a_single_leg_package_is_still_a_valid_package():
    legs = [Leg(1, "Diani", ARRIVAL, DEPARTURE, "Palmyra Shore Resort")]
    assert P.check(legs, arrival=ARRIVAL, departure=DEPARTURE) == []
    assert P.total_nights(legs) == 7
