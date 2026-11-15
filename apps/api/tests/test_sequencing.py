from __future__ import annotations

from decimal import Decimal

from app.modules.quotes.routing import Road
from app.modules.quotes.sequencing import (
    BETTER_ORDER,
    LONG_DRIVE,
    NO_ROAD,
    SHORT_STAY,
    Hop,
    hops_of,
    order_km,
    score,
    sequence,
    shortest_order,
)

D = Decimal

NETWORK: dict[tuple[str, str], tuple[str, int]] = {
    ("Nairobi", "Amboseli"): ("240", 300),
    ("Nairobi", "Mara"): ("270", 330),
    ("Nairobi", "Diani"): ("490", 600),
    ("Amboseli", "Mara"): ("560", 720),
    ("Amboseli", "Diani"): ("420", 540),
    ("Mara", "Diani"): ("700", 840),
}


def _road(a: str, b: str) -> Road | None:
    found = NETWORK.get((a, b)) or NETWORK.get((b, a))
    if found is None:
        return None
    km, minutes = found
    return Road(
        label=f"{a} to {b}",
        distance_km=D(km),
        drive_time_minutes=minutes,
        reversed_lookup=(a, b) not in NETWORK,
    )


def _sparse(a: str, b: str) -> Road | None:
    if {a, b} == {"Amboseli", "Mara"}:
        return None
    return _road(a, b)


def test_hops_are_the_drives_between_consecutive_legs():
    hops = hops_of(["Nairobi", "Mara", "Nairobi"], road_for=_road)
    assert [(hop.from_place, hop.to_place) for hop in hops] == [
        ("Nairobi", "Mara"),
        ("Mara", "Nairobi"),
    ]
    assert all(hop.road is not None for hop in hops)


def test_two_legs_in_one_place_are_not_a_drive():
    hops = hops_of(["Nairobi", "Nairobi", "Mara"], road_for=_road)
    assert [(hop.from_place, hop.to_place) for hop in hops] == [("Nairobi", "Mara")]


def test_a_hop_with_no_road_is_kept_rather_than_dropped():
    hops = hops_of(["Amboseli", "Mara"], road_for=_sparse)
    assert len(hops) == 1
    assert hops[0].road is None
    assert hops[0].minutes == 0 and hops[0].km == D(0)


def test_a_single_leg_package_has_no_hops():
    assert hops_of(["Diani"], road_for=_road) == []
    assert hops_of([], road_for=_road) == []


def test_the_score_adds_up_the_driving():
    result = score(hops_of(["Nairobi", "Mara", "Nairobi"], road_for=_road))
    assert result.total_km == D("540")
    assert result.total_minutes == 660
    assert result.total_hours == D("11.0")
    assert result.longest_minutes == 330
    assert result.hops == 2
    assert result.is_complete


def test_an_unknown_hop_is_counted_and_never_estimated():
    result = score(
        hops_of(["Nairobi", "Amboseli", "Mara", "Nairobi"], road_for=_sparse)
    )
    assert result.unknown_hops == 1
    assert not result.is_complete
    assert result.total_km == D("510")


def test_the_longest_drive_is_reported_separately():
    result = score(hops_of(["Nairobi", "Mara", "Diani"], road_for=_road))
    assert result.total_km == D("970")
    assert result.longest_minutes == 840


def test_the_shortest_order_keeps_the_ends_fixed():
    best = shortest_order(
        ["Nairobi", "Mara", "Amboseli", "Nairobi"], road_for=_road
    )
    assert best is not None
    ordering, total = best
    assert ordering[0] == "Nairobi" and ordering[-1] == "Nairobi"
    assert total == D("1070")


def test_a_genuinely_shorter_order_is_found():
    given = ["Diani", "Mara", "Amboseli", "Nairobi"]
    assert order_km(given, road_for=_road) == D("1500")
    best = shortest_order(given, road_for=_road)
    assert best is not None
    assert best[0] == ("Diani", "Amboseli", "Mara", "Nairobi")
    assert best[1] == D("1250")


def test_no_order_is_recommended_when_a_road_is_missing():
    assert (
        shortest_order(
            ["Nairobi", "Amboseli", "Mara", "Nairobi"], road_for=_sparse
        )
        is None
    )
    assert order_km(["Amboseli", "Mara"], road_for=_sparse) is None


def test_a_package_with_nothing_to_reorder_is_not_searched():
    assert shortest_order(["Nairobi", "Mara"], road_for=_road) is None
    assert shortest_order(["Nairobi", "Mara", "Nairobi"], road_for=_road) is None


def test_the_search_is_capped():
    long_trip = ["Nairobi"] + ["Mara"] * 8 + ["Nairobi"]
    assert shortest_order(long_trip, road_for=_road) is None


def test_a_missing_road_is_advisory_and_says_both_consequences():
    result = sequence(
        ["Nairobi", "Amboseli", "Mara", "Nairobi"], road_for=_sparse
    )
    faults = [p for p in result.problems if p.code == NO_ROAD]
    assert len(faults) == 1
    assert not faults[0].blocking
    assert "cannot be totalled" in faults[0].message
    assert "cannot be costed" in faults[0].message


def test_a_drive_past_the_working_day_is_reported_with_the_gate_in_mind():
    result = sequence(
        ["Nairobi", "Amboseli", "Mara", "Nairobi"],
        road_for=_road,
        max_drive_minutes=600,
    )
    fault = next(p for p in result.problems if p.code == LONG_DRIVE)
    assert not fault.blocking
    assert "12.0 hours" in fault.message
    assert "gate closes" in fault.message

    relaxed = sequence(
        ["Nairobi", "Amboseli", "Mara", "Nairobi"],
        road_for=_road,
        max_drive_minutes=780,
    )
    assert not [p for p in relaxed.problems if p.code == LONG_DRIVE]


def test_one_night_after_a_long_drive_is_flagged():
    result = sequence(
        ["Nairobi", "Mara", "Nairobi"],
        road_for=_road,
        nights=[1, 1, 0],
        max_drive_minutes=600,
    )
    fault = next(p for p in result.problems if p.code == SHORT_STAY)
    assert not fault.blocking
    assert "one night after about 5.5 hours" in fault.message


def test_a_comfortable_stay_after_a_long_drive_is_not_flagged():
    result = sequence(
        ["Nairobi", "Mara", "Nairobi"],
        road_for=_road,
        nights=[1, 3, 0],
        max_drive_minutes=600,
    )
    assert not [p for p in result.problems if p.code == SHORT_STAY]


def test_a_shorter_order_is_a_note_and_not_a_correction():
    result = sequence(
        ["Diani", "Mara", "Amboseli", "Nairobi"], road_for=_road, nights=[3, 2, 2, 1]
    )
    assert result.better_order == ("Diani", "Amboseli", "Mara", "Nairobi")
    assert result.saving_km == D("250")
    fault = next(p for p in result.problems if p.code == BETTER_ORDER)
    assert not fault.blocking
    assert "250 km less" in fault.message
    assert "may be deliberate" in fault.message


def test_an_order_that_is_already_shortest_gets_no_note():
    result = sequence(
        ["Diani", "Amboseli", "Mara", "Nairobi"], road_for=_road
    )
    assert result.better_order == ()
    assert result.saving_km == D(0)
    assert not [p for p in result.problems if p.code == BETTER_ORDER]


def test_every_sequencing_fault_is_advisory():
    result = sequence(
        ["Diani", "Mara", "Amboseli", "Nairobi"],
        road_for=_sparse,
        nights=[3, 1, 2, 1],
        max_drive_minutes=480,
    )
    assert result.problems
    assert all(not p.blocking for p in result.problems)


def test_the_same_package_scores_the_same_twice():
    places = ["Nairobi", "Mara", "Diani", "Nairobi"]
    first = sequence(places, road_for=_road)
    second = sequence(places, road_for=_road)
    assert first.score == second.score
    assert first.better_order == second.better_order
    assert [p.message for p in first.problems] == [p.message for p in second.problems]


def test_a_hop_carries_its_own_figures():
    hop = Hop(
        from_place="Nairobi",
        to_place="Mara",
        road=_road("Nairobi", "Mara"),
        nights_after=3,
    )
    assert hop.km == D("270")
    assert hop.minutes == 330
    assert hop.nights_after == 3
