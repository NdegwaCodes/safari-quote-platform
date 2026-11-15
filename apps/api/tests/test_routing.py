from __future__ import annotations

from decimal import Decimal

from app.modules.quotes.routing import (
    DAYS_PER_MOVEMENT,
    NO_ENDPOINTS,
    NO_FUEL_PRICE,
    NO_ROUTE,
    WRONG_VEHICLE,
    Road,
    check_endpoints,
    check_vehicle,
    missing_fuel_price,
    missing_route,
    normalise_types,
    vehicle_is_suitable,
)
from app.modules.vehicles.service import compute_transport_cost

D = Decimal


def _road(**over) -> Road:
    fields = {
        "label": "Nairobi to the Maasai Mara",
        "distance_km": D("270"),
        "drive_time_minutes": 330,
        "required_vehicle_types": ("safari_land_cruiser",),
    }
    fields.update(over)
    return Road(**fields)


def test_a_road_with_no_stated_requirement_takes_anything():
    road = _road(required_vehicle_types=())
    assert vehicle_is_suitable(road.required_vehicle_types, "saloon")
    assert check_vehicle(label="Transfer", road=road, offered="saloon") is None


def test_a_vehicle_the_road_does_not_take_is_blocking():
    road = _road()
    fault = check_vehicle(label="Nairobi to the Mara", road=road, offered="saloon")
    assert fault is not None
    assert fault.code == WRONG_VEHICLE
    assert fault.blocking
    assert "under-priced" in fault.message
    assert "cannot be run as sold" in fault.message
    assert "safari_land_cruiser" in fault.message


def test_the_vehicle_the_road_does_take_passes():
    road = _road()
    assert (
        check_vehicle(
            label="Nairobi to the Mara", road=road, offered="safari_land_cruiser"
        )
        is None
    )


def test_a_road_may_take_several_types():
    road = _road(required_vehicle_types=("safari_land_cruiser", "minibus_4x4"))
    assert vehicle_is_suitable(road.required_vehicle_types, "minibus_4x4")
    assert not vehicle_is_suitable(road.required_vehicle_types, "minibus")


def test_no_vehicle_at_all_is_not_suitable_for_a_road_that_asks():
    road = _road()
    assert not vehicle_is_suitable(road.required_vehicle_types, None)
    assert not vehicle_is_suitable(road.required_vehicle_types, "")
    fault = check_vehicle(label="Drive", road=road, offered=None)
    assert fault is not None and "no vehicle" in fault.message


def test_hand_entered_types_are_trimmed_and_case_folded():
    assert normalise_types([" 4X4 ", "4x4", "", None, "Saloon"]) == ("4x4", "saloon")
    assert vehicle_is_suitable(("4X4",), " 4x4 ")


def test_a_route_note_travels_with_the_fault():
    road = _road(notes="Last 40 km is murram; impassable after heavy rain.")
    fault = check_vehicle(label="Drive", road=road, offered="saloon")
    assert fault is not None
    assert "impassable after heavy rain" in fault.message.lower()


def test_a_drive_with_one_end_missing_says_which_end():
    missing_start = check_endpoints(
        label="Drive", has_origin=False, has_destination=True, sequence=2
    )
    assert missing_start is not None
    assert missing_start.code == NO_ENDPOINTS
    assert missing_start.blocking
    assert "no start" in missing_start.message
    assert missing_start.sequence == 2

    missing_end = check_endpoints(
        label="Drive", has_origin=True, has_destination=False
    )
    assert missing_end is not None and "no destination" in missing_end.message

    assert (
        check_endpoints(label="Drive", has_origin=True, has_destination=True) is None
    )


def test_a_road_with_no_row_is_blocking_and_says_what_to_enter():
    fault = missing_route(label="Nairobi to Amboseli", on="2026-07-04")
    assert fault.code == NO_ROUTE
    assert fault.blocking
    assert "no route on file" in fault.message
    assert "2026-07-04" in fault.message
    assert "driven kilometres" in fault.message


def test_a_missing_pump_price_is_its_own_fault():
    fault = missing_fuel_price(label="Drive", fuel_type="diesel")
    assert fault.code == NO_FUEL_PRICE
    assert fault.blocking
    assert "diesel" in fault.message
    assert "pump price" in fault.message


def test_drive_time_reads_in_hours_for_a_rate():
    assert _road(drive_time_minutes=330).hours == D("5.50")
    assert _road(drive_time_minutes=45).hours == D("0.75")


def test_a_movement_costs_one_day_of_its_crew():
    assert DAYS_PER_MOVEMENT == 1


def test_the_fuel_arithmetic_is_the_one_from_stage_2():
    calc = compute_transport_cost(
        distance_km=D("270"),
        consumption_kmpl=D("8"),
        fuel_price_per_litre=D("180"),
        days=DAYS_PER_MOVEMENT,
        driver_cost_per_day=D("3000"),
        daily_operating_cost=D("2000"),
    )
    assert calc["fuel_litres"] == D("33.75")
    assert calc["fuel_cost"] == D("6075.00")
    assert calc["driver_total"] == D("3000")
    assert calc["operating_total"] == D("2000")
    assert calc["total"] == D("11075.00")


def test_a_road_read_backwards_says_it_was():
    forward = _road(source="routes abc · 270 km, 330 min from 2026-01-01")
    assert not forward.reversed_lookup
    backwards = _road(reversed_lookup=True)
    assert backwards.reversed_lookup
