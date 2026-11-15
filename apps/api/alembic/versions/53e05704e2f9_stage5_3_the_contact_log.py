from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '53e05704e2f9'
down_revision: Union[str, Sequence[str], None] = '65fd3c1a37bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('communications',
    sa.Column('subject', sa.String(length=20), nullable=False),
    sa.Column('subject_id', sa.UUID(), nullable=False),
    sa.Column('channel', sa.String(length=40), nullable=False),
    sa.Column('direction', sa.String(length=20), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('subject_line', sa.String(length=200), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('reached', sa.Boolean(), nullable=True),
    sa.Column('duration_minutes', sa.Integer(), nullable=True),
    sa.Column('external_ref', sa.String(length=200), nullable=True),
    sa.Column('logged_by', sa.UUID(), nullable=True),
    sa.Column('amended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('amended_by', sa.UUID(), nullable=True),
    sa.Column('voided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('voided_by', sa.UUID(), nullable=True),
    sa.Column('void_reason', sa.Text(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("direction in ('inbound', 'outbound', 'internal')", name='ck_communication_direction'),
    sa.CheckConstraint("subject in ('lead', 'client', 'quote', 'booking')", name='ck_communication_subject'),
    sa.CheckConstraint('duration_minutes is null or (duration_minutes > 0 and reached is not false)', name='ck_communication_duration'),
    sa.ForeignKeyConstraint(['amended_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['logged_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['voided_by'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_communication_subject', 'communications', ['subject', 'subject_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_communications_occurred_at'), 'communications', ['occurred_at'], unique=False)
    op.add_column('leads', sa.Column('last_contact_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('leads', sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('leads', 'last_inbound_at')
    op.drop_column('leads', 'last_contact_at')
    op.drop_index(op.f('ix_communications_occurred_at'), table_name='communications')
    op.drop_index('ix_communication_subject', table_name='communications')
    op.drop_table('communications')
