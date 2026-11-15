from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c3bd52d1af'
down_revision: Union[str, Sequence[str], None] = '90dd20bbab6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('accommodations', sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('accommodations', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('accommodations', sa.Column('published_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_accommodations_is_published'), 'accommodations', ['is_published'], unique=False)
    op.add_column('activities', sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('activities', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('activities', sa.Column('published_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_activities_is_published'), 'activities', ['is_published'], unique=False)
    op.add_column('destinations', sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('destinations', sa.Column('published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('destinations', sa.Column('published_by', sa.UUID(), nullable=True))
    op.create_index(op.f('ix_destinations_is_published'), 'destinations', ['is_published'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_destinations_is_published'), table_name='destinations')
    op.drop_column('destinations', 'published_by')
    op.drop_column('destinations', 'published_at')
    op.drop_column('destinations', 'is_published')
    op.drop_index(op.f('ix_activities_is_published'), table_name='activities')
    op.drop_column('activities', 'published_by')
    op.drop_column('activities', 'published_at')
    op.drop_column('activities', 'is_published')
    op.drop_index(op.f('ix_accommodations_is_published'), table_name='accommodations')
    op.drop_column('accommodations', 'published_by')
    op.drop_column('accommodations', 'published_at')
    op.drop_column('accommodations', 'is_published')
