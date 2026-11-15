from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'bf98e7401b33'
down_revision: Union[str, Sequence[str], None] = '0ff0bb66eb7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('crew',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('roles', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('licence_number', sa.String(length=60), nullable=True),
    sa.Column('licence_expires_on', sa.Date(), nullable=True),
    sa.Column('guide_licence_number', sa.String(length=60), nullable=True),
    sa.Column('guide_licence_expires_on', sa.Date(), nullable=True),
    sa.Column('languages', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('supplier_id', sa.UUID(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['supplier_id'], ['suppliers.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_crew_active', 'crew', ['is_active'], unique=False)
    op.create_index(op.f('ix_crew_name'), 'crew', ['name'], unique=False)
    op.create_table('trip_assignments',
    sa.Column('booking_id', sa.UUID(), nullable=False),
    sa.Column('vehicle_id', sa.UUID(), nullable=True),
    sa.Column('crew_id', sa.UUID(), nullable=True),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('starts_on', sa.Date(), nullable=False),
    sa.Column('ends_on', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('override_reason', sa.Text(), nullable=True),
    sa.Column('assigned_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role in ('driver', 'guide', 'driver_guide', 'vehicle')", name='ck_assignment_role'),
    sa.CheckConstraint('(vehicle_id is null) <> (crew_id is null)', name='ck_assignment_one_subject'),
    sa.CheckConstraint('ends_on >= starts_on', name='ck_assignment_window'),
    sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['crew_id'], ['crew.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assignment_booking', 'trip_assignments', ['booking_id'], unique=False)
    op.create_index('ix_assignment_crew_dates', 'trip_assignments', ['crew_id', 'starts_on', 'ends_on'], unique=False)
    op.create_index('ix_assignment_vehicle_dates', 'trip_assignments', ['vehicle_id', 'starts_on', 'ends_on'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_assignment_vehicle_dates', table_name='trip_assignments')
    op.drop_index('ix_assignment_crew_dates', table_name='trip_assignments')
    op.drop_index('ix_assignment_booking', table_name='trip_assignments')
    op.drop_table('trip_assignments')
    op.drop_index(op.f('ix_crew_name'), table_name='crew')
    op.drop_index('ix_crew_active', table_name='crew')
    op.drop_table('crew')
