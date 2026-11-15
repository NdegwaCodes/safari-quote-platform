from __future__ import annotations

from datetime import date

from app.modules.quotes.itinerary import (
    ACTIVITY_OFF_TRIP,
    ACTIVITY_UNSCHEDULED,
    MOVEMENT_OFF_TRIP,
    MOVEMENT_UNDATED,
    NO_DAYS,
    Excursion,
    Movement,
    build,
    check,
    dates,
    programme,
)
from app.modules.quotes.packages import Leg

ARRIVAL, DEPARTURE = date(2026, 7, 1), date(2026, 7, 4)


def _leg(sequence, destination, check_in, check_out, *, board="FB", property_name=""):
    return Leg(
        sequence=sequence,
        destination=destination,
        check_in=check_in,
        check_out=check_out,
        property_name=property_name or f"{destination} Hotel",
        board=board,
    )


def _single():
    return [_leg(1, "Diani", ARRIVAL, DEPARTURE)]


def _package():
    return [
        _leg(1, "Nairobi", ARRIVAL, date(2026, 7, 2), board="BB"),
        _leg(2, "Maasai Mara", date(2026, 7, 2), DEPARTURE, board="FB"),
    ]


def test_a_trip_has_one_more_day_than_it_has_nights():
    assert len(dates(arrival=ARRIVAL, departure=DEPARTURE)) == 4
    days = build(_single(), arrival=ARRIVAL, departure=DEPARTURE)
    assert [day.number for day in days] == [1, 2, 3, 4]
    assert [day.on for day in days] == [
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 4),
    ]
    assert sum(1 for day in days if day.has_night) == 3


def test_the_first_and_last_days_are_marked():
    days = build(_single(), arrival=ARRIVAL, departure=DEPARTURE)
    assert days[0].is_arrival and not days[0].is_departure
    assert days[-1].is_departure and not days[-1].is_arrival
    assert not any(day.is_arrival or day.is_departure for day in days[1:-1])


def test_a_one_night_trip_is_two_days():
    days = build(
        [_leg(1, "Nairobi", ARRIVAL, date(2026, 7, 2))],
        arrival=ARRIVAL,
        departure=date(2026, 7, 2),
    )
    assert len(days) == 2
    assert days[0].has_night and not days[1].has_night


def test_a_departure_before_arrival_has_no_days_and_says_so():
    assert dates(arrival=DEPARTURE, departure=ARRIVAL) == []
    assert build(_single(), arrival=DEPARTURE, departure=ARRIVAL) == []
    problems = check(arrival=DEPARTURE, departure=ARRIVAL)
    assert [p.code for p in problems] == [NO_DAYS]
    assert problems[0].blocking


def test_a_same_day_trip_is_one_day():
    days = build([], arrival=ARRIVAL, departure=ARRIVAL)
    assert len(days) == 1
    assert days[0].is_arrival and days[0].is_departure


def test_a_day_belongs_to_the_leg_that_holds_its_night():
    days = build(_package(), arrival=ARRIVAL, departure=DEPARTURE)
    assert [day.destination for day in days] == [
        "Nairobi",
        "Maasai Mara",
        "Maasai Mara",
        "Maasai Mara",
    ]
    assert [day.leg for day in days] == [1, 2, 2, 2]


def test_the_departure_day_shows_the_property_they_woke_up_in():
    days = build(_package(), arrival=ARRIVAL, departure=DEPARTURE)
    last = days[-1]
    assert last.property_name == "Maasai Mara Hotel"
    assert last.board == ""
    assert not last.has_night


def test_board_is_the_board_of_the_leg_holding_that_night():
    days = build(_package(), arrival=ARRIVAL, departure=DEPARTURE)
    assert [day.board for day in days] == ["BB", "FB", "FB", ""]


def test_legs_are_read_in_sequence_and_not_in_date_order():
    swapped = [
        _leg(2, "Nairobi", ARRIVAL, date(2026, 7, 2), board="BB"),
        _leg(1, "Maasai Mara", date(2026, 7, 2), DEPARTURE),
    ]
    days = build(swapped, arrival=ARRIVAL, departure=DEPARTURE)
    assert days[0].destination == "Nairobi"
    assert days[0].leg == 2


def test_a_day_no_leg_covers_is_left_blank_rather_than_guessed():
    days = build(
        [_leg(1, "Diani", ARRIVAL, date(2026, 7, 2))],
        arrival=ARRIVAL,
        departure=DEPARTURE,
    )
    assert days[1].destination == ""
    assert days[1].property_name == ""
    assert days[1].leg is None
    assert days[-1].destination == "Diani"


def test_a_movement_lands_on_the_date_it_runs():
    days = build(
        _single(),
        arrival=ARRIVAL,
        departure=DEPARTURE,
        movements=[
            Movement(1, "transfer", "road", "Airport to hotel", on=ARRIVAL),
            Movement(2, "transfer", "road", "Hotel to airport", on=DEPARTURE),
        ],
    )
    assert [one.label for one in days[0].movements] == ["Airport to hotel"]
    assert days[1].movements == ()
    assert [one.label for one in days[-1].movements] == ["Hotel to airport"]


def test_an_undated_movement_appears_on_no_day_and_is_reported():
    movements = [Movement(1, "line_haul", "rail", "Nairobi to Mombasa")]
    days = build(
        _single(), arrival=ARRIVAL, departure=DEPARTURE, movements=movements
    )
    assert all(day.movements == () for day in days)
    problems = check(arrival=ARRIVAL, departure=DEPARTURE, movements=movements)
    assert [p.code for p in problems] == [MOVEMENT_UNDATED]
    assert not problems[0].blocking
    assert "does not appear on the day-by-day" in problems[0].message


def test_a_movement_dated_outside_the_trip_is_blocking():
    problems = check(
        arrival=ARRIVAL,
        departure=DEPARTURE,
        movements=[
            Movement(1, "transfer", "road", "Airport to hotel", on=date(2026, 8, 9))
        ],
    )
    assert [p.code for p in problems] == [MOVEMENT_OFF_TRIP]
    assert problems[0].blocking
    assert problems[0].sequence == 1


def test_several_movements_on_one_day_keep_their_order():
    days = build(
        _single(),
        arrival=ARRIVAL,
        departure=DEPARTURE,
        movements=[
            Movement(3, "transfer", "road", "Terminus to hotel", on=ARRIVAL),
            Movement(1, "transfer", "road", "Hotel to terminus", on=ARRIVAL),
            Movement(2, "line_haul", "rail", "SGR", on=ARRIVAL),
        ],
    )
    assert [one.label for one in days[0].movements] == [
        "Hotel to terminus",
        "SGR",
        "Terminus to hotel",
    ]


def test_an_excursion_lands_on_the_day_number_it_was_scheduled_for():
    days = build(
        _single(),
        arrival=ARRIVAL,
        departure=DEPARTURE,
        excursions=[Excursion("Sunset dhow cruise", day=2)],
    )
    assert days[0].excursions == ()
    assert days[1].excursions == ("Sunset dhow cruise",)


def test_an_excursion_scheduled_off_the_trip_is_blocking():
    problems = check(
        arrival=ARRIVAL,
        departure=DEPARTURE,
        excursions=[Excursion("Wasini Island day", day=9)],
    )
    assert [p.code for p in problems] == [ACTIVITY_OFF_TRIP]
    assert problems[0].blocking
    assert "day 9" in problems[0].message and "4 day(s)" in problems[0].message


def test_the_last_day_is_a_valid_day_for_an_excursion():
    assert (
        check(
            arrival=ARRIVAL,
            departure=DEPARTURE,
            excursions=[Excursion("Farewell brunch cruise", day=4)],
        )
        == []
    )


def test_an_unscheduled_excursion_is_charged_and_reported():
    excursions = [Excursion("Reef snorkelling", day=None)]
    days = build(
        _single(), arrival=ARRIVAL, departure=DEPARTURE, excursions=excursions
    )
    assert all(day.excursions == () for day in days)
    problems = check(arrival=ARRIVAL, departure=DEPARTURE, excursions=excursions)
    assert [p.code for p in problems] == [ACTIVITY_UNSCHEDULED]
    assert not problems[0].blocking
    assert "charged but does not appear" in problems[0].message


def test_two_excursions_on_one_day_both_appear():
    days = build(
        _single(),
        arrival=ARRIVAL,
        departure=DEPARTURE,
        excursions=[
            Excursion("Reef snorkelling", day=2),
            Excursion("Sunset dhow cruise", day=2),
        ],
    )
    assert days[1].excursions == ("Reef snorkelling", "Sunset dhow cruise")


def test_programme_returns_the_days_and_the_faults_together():
    result = programme(
        _package(),
        arrival=ARRIVAL,
        departure=DEPARTURE,
        movements=[Movement(1, "transfer", "road", "Airport to hotel")],
        excursions=[Excursion("Balloon safari", day=3)],
    )
    assert len(result.days) == 4
    assert result.days[2].excursions == ("Balloon safari",)
    assert [p.code for p in result.problems] == [MOVEMENT_UNDATED]


def test_the_programme_is_the_same_twice():
    kwargs = {
        "arrival": ARRIVAL,
        "departure": DEPARTURE,
        "movements": [Movement(1, "transfer", "road", "Airport to hotel", on=ARRIVAL)],
        "excursions": [Excursion("Balloon safari", day=3)],
    }
    assert build(_package(), **kwargs) == build(_package(), **kwargs)


def test_the_journey_is_laid_onto_every_package_unchanged():
    movements = [Movement(1, "transfer", "road", "Airport to hotel", on=ARRIVAL)]
    one = build(_single(), arrival=ARRIVAL, departure=DEPARTURE, movements=movements)
    two = build(_package(), arrival=ARRIVAL, departure=DEPARTURE, movements=movements)
    assert one[0].movements == two[0].movements


def test_the_day_a_package_changes_hotels_names_both():
    days = build(_package(), arrival=ARRIVAL, departure=DEPARTURE)
    assert days[0].moves_from == ""
    assert days[1].moves_from == "Nairobi Hotel"
    assert days[1].property_name == "Maasai Mara Hotel"
    assert [day.moves_from for day in days[2:]] == ["", ""]


def test_a_single_property_option_never_moves():
    days = build(_single(), arrival=ARRIVAL, departure=DEPARTURE)
    assert all(day.moves_from == "" for day in days)


def test_a_gap_does_not_invent_a_move():
    days = build(
        [
            _leg(1, "Diani", ARRIVAL, date(2026, 7, 2)),
            _leg(2, "Diani", date(2026, 7, 3), DEPARTURE),
        ],
        arrival=ARRIVAL,
        departure=DEPARTURE,
    )
    assert days[1].leg is None
    assert days[1].moves_from == ""
    assert days[2].moves_from == "Diani Hotel"
