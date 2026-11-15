from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '15c4d3d4af6b'
down_revision: Union[str, Sequence[str], None] = '316e59973b79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quote_rejected_candidates",
        sa.Column(
            "source",
            sa.String(length=10),
            server_default=sa.text("'engine'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("quote_rejected_candidates", "source")
