from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'bff02a79fd8c'
down_revision: Union[str, Sequence[str], None] = 'bf98e7401b33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('trip_logs',
    sa.Column('assignment_id', sa.UUID(), nullable=False),
    sa.Column('vehicle_id', sa.UUID(), nullable=False),
    sa.Column('booking_id', sa.UUID(), nullable=False),
    sa.Column('odometer_out_km', sa.Numeric(precision=12, scale=1), nullable=False),
    sa.Column('odometer_in_km', sa.Numeric(precision=12, scale=1), nullable=True),
    sa.Column('started_on', sa.Date(), nullable=False),
    sa.Column('ended_on', sa.Date(), nullable=True),
    sa.Column('driver_id', sa.UUID(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('recorded_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('odometer_in_km is null or odometer_in_km >= odometer_out_km', name='ck_trip_log_odometer'),
    sa.CheckConstraint('odometer_out_km >= 0', name='ck_trip_log_out_positive'),
    sa.ForeignKeyConstraint(['assignment_id'], ['trip_assignments.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['driver_id'], ['crew.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('assignment_id', name='uq_trip_log_assignment')
    )
    op.create_index('ix_trip_log_vehicle', 'trip_logs', ['vehicle_id', 'started_on'], unique=False)
    op.create_table('fuel_fills',
    sa.Column('trip_log_id', sa.UUID(), nullable=False),
    sa.Column('litres', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('bought_on', sa.Date(), nullable=False),
    sa.Column('station', sa.String(length=160), nullable=True),
    sa.Column('receipt_ref', sa.String(length=80), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('recorded_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('amount > 0', name='ck_fuel_fill_amount'),
    sa.CheckConstraint('litres > 0', name='ck_fuel_fill_litres'),
    sa.ForeignKeyConstraint(['recorded_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['trip_log_id'], ['trip_logs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_fuel_fill_log', 'fuel_fills', ['trip_log_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_fuel_fill_log', table_name='fuel_fills')
    op.drop_table('fuel_fills')
    op.drop_index('ix_trip_log_vehicle', table_name='trip_logs')
    op.drop_table('trip_logs')
