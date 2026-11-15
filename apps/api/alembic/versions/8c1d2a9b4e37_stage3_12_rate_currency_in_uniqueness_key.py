from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "8c1d2a9b4e37"
down_revision: Union[str, Sequence[str], None] = "072fce0720a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NAME = "uq_accommodation_rate_period"
_COLUMNS = [
    "room_type_id",
    "meal_plan_id",
    "residence_category_id",
    "occupancy",
    "effective_from",
]


def upgrade() -> None:
    op.drop_constraint(_NAME, "accommodation_rates", type_="unique")
    op.create_unique_constraint(_NAME, "accommodation_rates", [*_COLUMNS, "currency"])


def downgrade() -> None:
    op.drop_constraint(_NAME, "accommodation_rates", type_="unique")
    op.create_unique_constraint(_NAME, "accommodation_rates", _COLUMNS)
