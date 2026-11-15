from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a3e81c60b9"
down_revision: Union[str, Sequence[str], None] = "c72ba3d81f45"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote_transport_segments",
        sa.Column("travel_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quote_transport_segments", "travel_date")
