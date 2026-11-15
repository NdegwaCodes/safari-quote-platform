from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '072fce0720a1'
down_revision: Union[str, Sequence[str], None] = '15c4d3d4af6b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('quotes', sa.Column('document_title', sa.String(length=160), nullable=True))
    op.add_column('quotes', sa.Column('document_subtitle', sa.String(length=240), nullable=True))


def downgrade() -> None:
    op.drop_column('quotes', 'document_subtitle')
    op.drop_column('quotes', 'document_title')
