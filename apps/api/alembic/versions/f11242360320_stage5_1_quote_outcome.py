from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f11242360320'
down_revision: Union[str, Sequence[str], None] = '8b87b4cdb902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quotes', sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('quotes', sa.Column('decided_by', sa.UUID(), nullable=True))
    op.add_column('quotes', sa.Column('decision_note', sa.Text(), nullable=True))
    op.create_foreign_key(None, 'quotes', 'users', ['decided_by'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint(None, 'quotes', type_='foreignkey')
    op.drop_column('quotes', 'decision_note')
    op.drop_column('quotes', 'decided_by')
    op.drop_column('quotes', 'decided_at')
