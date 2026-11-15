from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '35fbeba979af'
down_revision: Union[str, Sequence[str], None] = 'b1c3bd52d1af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bookings', sa.Column('retained_amount', sa.Numeric(precision=14, scale=2), nullable=True))
    op.add_column('bookings', sa.Column('cancellation_band', sa.String(length=20), nullable=True))
    op.add_column('bookings', sa.Column('cancellation_notice_days', sa.Integer(), nullable=True))
    op.add_column('bookings', sa.Column('is_exclusive_use', sa.Boolean(), server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('bookings', 'is_exclusive_use')
    op.drop_column('bookings', 'cancellation_notice_days')
    op.drop_column('bookings', 'cancellation_band')
    op.drop_column('bookings', 'retained_amount')
