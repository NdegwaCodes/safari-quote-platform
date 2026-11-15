from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

MIN_KM_FOR_CONSUMPTION = Decimal("100")

DEFAULT_TOLERANCE_PCT = Decimal("10")

UNACCOUNTED_KM = "vehicle_unaccounted_km"
MODEL_OPTIMISTIC = "vehicle_consumption_optimistic"
MODEL_PESSIMISTIC = "vehicle_consumption_pessimistic"
NOT_ENOUGH_DATA = "vehicle_not_enough_data"


class LogRefused(ValueError):
    pass


@dataclass(frozen=True)
class Odometer:

    out_km: Decimal
    in_km: Decimal | None = None

    @property
    def distance(self) -> Decimal | None:
        if self.in_km is None:
            return None
        return self.in_km - self.out_km


def check_reading(
    reading: Odometer, *, previous_in: Decimal | None = None
) -> list[str]:
    if reading.out_km < 0 or (reading.in_km is not None and reading.in_km < 0):
        raise LogRefused("An odometer reading cannot be negative.")
    if reading.in_km is not None and reading.in_km < reading.out_km:
        raise LogRefused(
            f"The vehicle came back on {_plain(reading.in_km)} km having left "
            f"on {_plain(reading.out_km)}. An odometer does not run backwards "
            f"— check the digits."
        )
    if previous_in is not None and reading.out_km < previous_in:
        raise LogRefused(
            f"This trip leaves on {_plain(reading.out_km)} km and the vehicle's "
            f"last trip came back on {_plain(previous_in)}. One of the two "
            f"readings is wrong."
        )
    notes: list[str] = []
    if previous_in is not None and reading.out_km > previous_in:
        gap = reading.out_km - previous_in
        notes.append(
            f"{_plain(gap)} km since the vehicle last came back, on no trip. "
            f"Repositioning, a service run, or somebody's weekend — worth "
            f"knowing which."
        )
    return notes


@dataclass(frozen=True)
class Fill:

    litres: Decimal
    amount: Decimal
    currency: str
    bought_on: date | None = None

    @property
    def price_per_litre(self) -> Decimal | None:
        if self.litres <= 0:
            return None
        return (self.amount / self.litres).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


def check_fill(fill: Fill) -> None:
    if fill.litres <= 0:
        raise LogRefused(
            "A fuel purchase has to have litres on it. A receipt with only a "
            "shilling figure cannot tell you anything about consumption."
        )
    if fill.amount <= 0:
        raise LogRefused("A fuel purchase has to have an amount on it.")
    if len((fill.currency or "").strip()) != 3:
        raise LogRefused(
            "A fuel purchase needs a currency. Money is an amount and a "
            "currency here as everywhere else."
        )


def fuel_total(fills: Sequence[Fill]) -> tuple[Decimal, Decimal, str]:
    if not fills:
        return Decimal(0), Decimal(0), ""
    currencies = {fill.currency.upper() for fill in fills}
    if len(currencies) > 1:
        raise LogRefused(
            "This trip's fuel was bought in "
            + ", ".join(sorted(currencies))
            + ". Totalling them would mean choosing an exchange rate, which is "
            "a decision and not arithmetic."
        )
    return (
        sum((fill.litres for fill in fills), Decimal(0)),
        sum((fill.amount for fill in fills), Decimal(0)),
        currencies.pop(),
    )


@dataclass
class Actual:

    distance_km: Decimal | None = None
    litres: Decimal = Decimal(0)
    fuel_cost: Decimal = Decimal(0)
    currency: str = ""
    model_kmpl: Decimal | None = None
    actual_kmpl: Decimal | None = None

    @property
    def variance_pct(self) -> Decimal | None:
        if not self.model_kmpl or self.actual_kmpl is None:
            return None
        return (
            (self.actual_kmpl - self.model_kmpl) / self.model_kmpl * 100
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def model_litres(self) -> Decimal | None:
        if not self.model_kmpl or self.distance_km is None:
            return None
        return (self.distance_km / self.model_kmpl).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


def measure(
    *,
    odometer: Odometer | None,
    fills: Sequence[Fill],
    model_kmpl: Decimal | None,
    min_km: Decimal = MIN_KM_FOR_CONSUMPTION,
) -> Actual:
    litres, cost, currency = fuel_total(fills)
    distance = odometer.distance if odometer is not None else None
    out = Actual(
        distance_km=distance,
        litres=litres,
        fuel_cost=cost,
        currency=currency,
        model_kmpl=model_kmpl,
    )
    if distance is not None and distance >= min_km and litres > 0:
        out.actual_kmpl = (distance / litres).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return out


@dataclass(frozen=True)
class Finding:

    code: str
    message: str
    trips: int = 0
    model_kmpl: Decimal | None = None
    actual_kmpl: Decimal | None = None
    variance_pct: Decimal | None = None


@dataclass
class FleetTruth:

    vehicle: str = ""
    trips: int = 0
    distance_km: Decimal = Decimal(0)
    litres: Decimal = Decimal(0)
    fuel_cost: Decimal = Decimal(0)
    currency: str = ""
    model_kmpl: Decimal | None = None
    findings: list[Finding] = field(default_factory=list)

    @property
    def actual_kmpl(self) -> Decimal | None:
        if self.litres <= 0 or self.distance_km <= 0:
            return None
        return (self.distance_km / self.litres).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )


def audit(
    vehicle: str,
    actuals: Iterable[Actual],
    *,
    model_kmpl: Decimal | None,
    tolerance_pct: Decimal = DEFAULT_TOLERANCE_PCT,
    min_trips: int = 3,
) -> FleetTruth:
    measured = [
        one
        for one in actuals
        if one.distance_km is not None and one.distance_km > 0 and one.litres > 0
    ]
    out = FleetTruth(vehicle=vehicle, model_kmpl=model_kmpl)
    currencies = {one.currency for one in measured if one.currency}
    out.currency = currencies.pop() if len(currencies) == 1 else ""
    for one in measured:
        out.trips += 1
        out.distance_km += one.distance_km or Decimal(0)
        out.litres += one.litres
        if out.currency and one.currency == out.currency:
            out.fuel_cost += one.fuel_cost

    actual = out.actual_kmpl
    if out.trips < min_trips or actual is None:
        out.findings.append(
            Finding(
                NOT_ENOUGH_DATA,
                f"{vehicle} has {out.trips} measured trip(s). Not enough to say "
                f"anything about the model figure — two trips and a hill is not "
                f"a pattern.",
                trips=out.trips,
                model_kmpl=model_kmpl,
                actual_kmpl=actual,
            )
        )
        return out

    if not model_kmpl:
        return out
    variance = ((actual - model_kmpl) / model_kmpl * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    if abs(variance) < tolerance_pct:
        return out

    shortfall = abs(variance).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if variance < 0:
        out.findings.append(
            Finding(
                MODEL_OPTIMISTIC,
                f"{vehicle} is priced at {_plain(model_kmpl)} km/L and has "
                f"managed {_plain(actual)} over {out.trips} trips "
                f"({_plain(out.distance_km)} km). Every quote using it is "
                f"under-costing fuel by about {_plain(shortfall)}%. Somebody "
                f"has to decide whether that is the new truth — nothing here "
                f"changes it.",
                trips=out.trips,
                model_kmpl=model_kmpl,
                actual_kmpl=actual,
                variance_pct=variance,
            )
        )
    else:
        out.findings.append(
            Finding(
                MODEL_PESSIMISTIC,
                f"{vehicle} is priced at {_plain(model_kmpl)} km/L and has "
                f"managed {_plain(actual)} over {out.trips} trips. Quotes using "
                f"it carry about {_plain(shortfall)}% more fuel than it burns — "
                f"harmless to the margin, and it is losing work on price.",
                trips=out.trips,
                model_kmpl=model_kmpl,
                actual_kmpl=actual,
                variance_pct=variance,
            )
        )
    return out


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


__all__ = [
    "DEFAULT_TOLERANCE_PCT",
    "MIN_KM_FOR_CONSUMPTION",
    "MODEL_OPTIMISTIC",
    "MODEL_PESSIMISTIC",
    "NOT_ENOUGH_DATA",
    "UNACCOUNTED_KM",
    "Actual",
    "Fill",
    "Finding",
    "FleetTruth",
    "LogRefused",
    "Odometer",
    "audit",
    "check_fill",
    "check_reading",
    "fuel_total",
    "measure",
]
