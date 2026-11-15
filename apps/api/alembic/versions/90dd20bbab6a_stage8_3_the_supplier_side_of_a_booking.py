from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '90dd20bbab6a'
down_revision: Union[str, Sequence[str], None] = 'bff02a79fd8c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('supplier_bookings',
    sa.Column('booking_id', sa.UUID(), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=False),
    sa.Column('service', sa.String(length=300), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('their_reference', sa.String(length=120), nullable=True),
    sa.Column('check_in', sa.Date(), nullable=True),
    sa.Column('check_out', sa.Date(), nullable=True),
    sa.Column('confirm_by', sa.Date(), nullable=True),
    sa.Column('expected_amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('invoiced_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('settled_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('requested_on', sa.Date(), nullable=True),
    sa.Column('confirmed_on', sa.Date(), nullable=True),
    sa.Column('settled_on', sa.Date(), nullable=True),
    sa.Column('cancel_reason', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status in ('to_request', 'requested', 'confirmed', 'cancelled')", name='ck_supplier_booking_status'),
    sa.CheckConstraint('check_out is null or check_in is null or check_out >= check_in', name='ck_supplier_booking_dates'),
    sa.CheckConstraint('expected_amount >= 0', name='ck_supplier_booking_expected'),
    sa.CheckConstraint('invoiced_amount is null or invoiced_amount >= 0', name='ck_supplier_booking_invoiced'),
    sa.CheckConstraint('settled_amount is null or settled_amount >= 0', name='ck_supplier_booking_settled'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_supplier_booking_booking', 'supplier_bookings', ['booking_id'], unique=False)
    op.create_index('ix_supplier_booking_supplier', 'supplier_bookings', ['supplier_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_supplier_booking_supplier', table_name='supplier_bookings')
    op.drop_index('ix_supplier_booking_booking', table_name='supplier_bookings')
    op.drop_table('supplier_bookings')
