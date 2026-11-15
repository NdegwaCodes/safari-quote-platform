from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '9ed0fe038498'
down_revision: Union[str, Sequence[str], None] = 'd5a3e81c60b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('routes',
    sa.Column('origin_id', sa.UUID(), nullable=False),
    sa.Column('destination_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=True),
    sa.Column('distance_km', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('drive_time_minutes', sa.Integer(), nullable=False),
    sa.Column('required_vehicle_types', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('distance_km > 0', name='ck_route_distance_positive'),
    sa.CheckConstraint('drive_time_minutes > 0', name='ck_route_drive_time_positive'),
    sa.CheckConstraint('origin_id <> destination_id', name='ck_route_endpoints_differ'),
    sa.ForeignKeyConstraint(['destination_id'], ['destinations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['origin_id'], ['destinations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('origin_id', 'destination_id', 'effective_from', name='uq_route_period')
    )
    op.create_index(op.f('ix_routes_destination_id'), 'routes', ['destination_id'], unique=False)
    op.create_index(op.f('ix_routes_effective_from'), 'routes', ['effective_from'], unique=False)
    op.create_index(op.f('ix_routes_effective_to'), 'routes', ['effective_to'], unique=False)
    op.create_index(op.f('ix_routes_origin_id'), 'routes', ['origin_id'], unique=False)
    op.add_column(
        'quote_transport_segments',
        sa.Column('origin_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_quote_transport_segments_origin',
        'quote_transport_segments',
        'destinations',
        ['origin_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_quote_transport_segments_origin',
        'quote_transport_segments',
        type_='foreignkey',
    )
    op.drop_column('quote_transport_segments', 'origin_id')
    op.drop_index(op.f('ix_routes_origin_id'), table_name='routes')
    op.drop_index(op.f('ix_routes_effective_to'), table_name='routes')
    op.drop_index(op.f('ix_routes_effective_from'), table_name='routes')
    op.drop_index(op.f('ix_routes_destination_id'), table_name='routes')
    op.drop_table('routes')
