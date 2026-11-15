from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.modules.destinations.models import Destination
from app.modules.park_fees.models import ParkFee
from app.modules.residence.models import ResidenceCategory

KWS_FROM = date(2025, 10, 1)
KWS_TO = date(2030, 12, 31)

KWS_CATEGORIES: dict[str, dict[str, tuple[str, str, str]]] = {
    "premium": {
        "citizen": ("1500", "750", "KES"),
        "ea_resident": ("1500", "750", "KES"),
        "resident": ("2025", "1050", "KES"),
        "non_resident": ("90", "45", "USD"),
        "african_citizen": ("50", "25", "USD"),
    },
    "urban": {
        "citizen": ("1000", "500", "KES"),
        "ea_resident": ("1000", "500", "KES"),
        "resident": ("1350", "675", "KES"),
        "non_resident": ("80", "40", "USD"),
        "african_citizen": ("40", "20", "USD"),
    },
    "wilderness_tsavo": {
        "citizen": ("1000", "500", "KES"),
        "ea_resident": ("1000", "500", "KES"),
        "resident": ("1350", "675", "KES"),
        "non_resident": ("80", "40", "USD"),
        "african_citizen": ("40", "20", "USD"),
    },
    "wilderness_meru": {
        "citizen": ("800", "500", "KES"),
        "ea_resident": ("800", "500", "KES"),
        "resident": ("1100", "675", "KES"),
        "non_resident": ("70", "40", "USD"),
        "african_citizen": ("40", "20", "USD"),
    },
    "mountain": {
        "citizen": ("800", "400", "KES"),
        "ea_resident": ("800", "400", "KES"),
        "resident": ("1100", "550", "KES"),
        "non_resident": ("70", "35", "USD"),
        "african_citizen": ("30", "15", "USD"),
    },
    "scenic": {
        "citizen": ("500", "250", "KES"),
        "ea_resident": ("500", "250", "KES"),
        "resident": ("675", "350", "KES"),
        "non_resident": ("50", "25", "USD"),
        "african_citizen": ("20", "10", "USD"),
    },
    "special_interest": {
        "citizen": ("500", "250", "KES"),
        "ea_resident": ("500", "250", "KES"),
        "resident": ("675", "350", "KES"),
        "non_resident": ("40", "20", "USD"),
        "african_citizen": ("20", "10", "USD"),
    },
    "sanctuary": {
        "citizen": ("300", "200", "KES"),
        "ea_resident": ("300", "200", "KES"),
        "resident": ("405", "300", "KES"),
        "non_resident": ("25", "15", "USD"),
        "african_citizen": ("15", "10", "USD"),
    },
    "marine": {
        "citizen": ("500", "250", "KES"),
        "ea_resident": ("500", "250", "KES"),
        "resident": ("675", "350", "KES"),
        "non_resident": ("25", "15", "USD"),
        "african_citizen": ("15", "10", "USD"),
    },
}

KWS_PARKS: tuple[tuple[str, str, str, str], ...] = (
    ("Amboseli National Park", "premium", "park", "Rift Valley"),
    ("Lake Nakuru National Park", "premium", "park", "Rift Valley"),
    ("Nairobi National Park", "urban", "park", "Nairobi"),
    ("Tsavo East National Park", "wilderness_tsavo", "park", "Coast"),
    ("Tsavo West National Park", "wilderness_tsavo", "park", "Coast"),
    ("Meru National Park", "wilderness_meru", "park", "Eastern"),
    ("Aberdare National Park", "wilderness_meru", "park", "Central"),
    ("Mount Kenya National Park", "mountain", "park", "Central"),
    ("Hell's Gate National Park", "scenic", "park", "Rift Valley"),
    ("Mount Longonot National Park", "scenic", "park", "Rift Valley"),
    ("Shimba Hills National Reserve", "scenic", "reserve", "Coast"),
    ("Nairobi Safari Walk", "sanctuary", "sanctuary", "Nairobi"),
    ("Nairobi Animal Orphanage", "sanctuary", "sanctuary", "Nairobi"),
    ("Kisite Mpunguti Marine National Park", "marine", "marine", "Coast"),
    ("Diani Chale Marine National Reserve", "marine", "marine", "Coast"),
    ("Watamu Marine National Park", "marine", "marine", "Coast"),
    ("Mombasa Marine National Park", "marine", "marine", "Coast"),
    ("Malindi Marine National Park", "marine", "marine", "Coast"),
)

KWS_CHILD_MIN = 6
KWS_CHILD_MAX = 17

MARA_SEASONS: tuple[
    tuple[str, date, date, dict[str, tuple[str, str, int, int, str]]], ...
] = (
    (
        "Green season",
        date(2026, 1, 1),
        date(2026, 6, 30),
        {
            "citizen": ("1500", "600", 3, 17, "KES"),
            "ea_resident": ("2500", "1000", 3, 17, "KES"),
            "non_resident": ("100", "50", 9, 17, "USD"),
        },
    ),
    (
        "Peak season",
        date(2026, 7, 1),
        date(2026, 12, 31),
        {
            "citizen": ("2000", "800", 3, 17, "KES"),
            "ea_resident": ("5000", "1500", 3, 17, "KES"),
            "non_resident": ("200", "50", 9, 17, "USD"),
        },
    ),
)

VEHICLE_DAY_CHARGES_KES: tuple[tuple[int, int, str], ...] = (
    (1, 5, "600"),
    (6, 12, "1500"),
    (13, 24, "3000"),
    (25, 44, "4500"),
    (45, 200, "5000"),
)

MICE_SOURCE_NOTE = (
    "KWS prints 'Amount of fees: 30% of the applicable park entry fees' for a "
    "100+ group down to 5% for a 10-29 group. Read literally the group PAYS that "
    "percentage, which would make a small group's deal far better than a large "
    "one's and inverts the ladder. The wording is ambiguous; the only monotonic "
    "reading is a DISCOUNT of that percentage, and that is what is modelled — "
    "switched off until KWS confirms it, because claiming a 95% reduction we are "
    "not owed is a loss nobody notices."
)


async def _destination(db: AsyncSession, name: str, kind: str, region: str) -> Destination:
    slug = name.lower().replace("'", "").replace(".", "").replace(" ", "-")
    existing = (
        await db.execute(select(Destination).where(Destination.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    destination = Destination(
        name=name, slug=slug, type=kind, country="Kenya", region=region
    )
    db.add(destination)
    await db.flush()
    return destination


async def _fee(
    db: AsyncSession,
    *,
    destination_id,
    residence_id,
    currency: str,
    adult: str,
    child: str,
    child_min: int,
    child_max: int,
    starts: date,
    ends: date,
) -> str:
    existing = (
        await db.execute(
            select(ParkFee).where(
                ParkFee.destination_id == destination_id,
                ParkFee.fee_type == "park_entry",
                ParkFee.residence_category_id == residence_id,
                ParkFee.effective_from == starts,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        wanted = (Decimal(adult), Decimal(child), currency, child_min, child_max, ends)
        current = (
            existing.adult,
            existing.child,
            existing.currency,
            existing.child_min_age,
            existing.child_max_age,
            existing.effective_to,
        )
        if current == wanted:
            return "same"
        (
            existing.adult,
            existing.child,
            existing.currency,
            existing.child_min_age,
            existing.child_max_age,
            existing.effective_to,
        ) = wanted
        return "corrected"
    db.add(
        ParkFee(
            destination_id=destination_id,
            fee_type="park_entry",
            residence_category_id=residence_id,
            currency=currency,
            adult=Decimal(adult),
            child=Decimal(child),
            infant=Decimal(0),
            child_min_age=child_min,
            child_max_age=child_max,
            effective_from=starts,
            effective_to=ends,
        )
    )
    return "created"


async def seed_park_fees(db: AsyncSession) -> dict[str, int]:
    categories = {
        row.key: row
        for row in (await db.execute(select(ResidenceCategory))).scalars().all()
    }
    missing = {
        key
        for table in KWS_CATEGORIES.values()
        for key in table
        if key not in categories
    }
    if missing:
        raise RuntimeError(
            f"residence categories {sorted(missing)} are not seeded; "
            "run `python -m app.db.seed` first"
        )

    tally = {"created": 0, "corrected": 0, "same": 0}
    parks = 0
    for name, category, kind, region in KWS_PARKS:
        destination = await _destination(db, name, kind, region)
        parks += 1
        for residence_key, (adult, child, currency) in KWS_CATEGORIES[category].items():
            residence = categories[residence_key]
            tally[
                await _fee(
                    db,
                    destination_id=destination.id,
                    residence_id=residence.id,
                    currency=currency,
                    adult=adult,
                    child=child,
                    child_min=KWS_CHILD_MIN,
                    child_max=KWS_CHILD_MAX,
                    starts=KWS_FROM,
                    ends=KWS_TO,
                )
            ] += 1

    mara = await _destination(
        db, "Maasai Mara National Reserve", "reserve", "Rift Valley"
    )
    parks += 1
    for _season, starts, ends, table in MARA_SEASONS:
        for residence_key, (adult, child, cmin, cmax, currency) in table.items():
            residence = categories[residence_key]
            tally[
                await _fee(
                    db,
                    destination_id=mara.id,
                    residence_id=residence.id,
                    currency=currency,
                    adult=adult,
                    child=child,
                    child_min=cmin,
                    child_max=cmax,
                    starts=starts,
                    ends=ends,
                )
            ] += 1

    await db.commit()
    return {
        "destinations": parks,
        "fees_created": tally["created"],
        "fees_corrected": tally["corrected"],
        "fees_unchanged": tally["same"],
    }


async def _main() -> None:
    async with AsyncSessionLocal() as db:
        result = await seed_park_fees(db)
    print(
        f"[seed_park_fees] {result['destinations']} destinations, "
        f"{result['fees_created']} created, {result['fees_corrected']} corrected, "
        f"{result['fees_unchanged']} unchanged"
    )


if __name__ == "__main__":
    asyncio.run(_main())
