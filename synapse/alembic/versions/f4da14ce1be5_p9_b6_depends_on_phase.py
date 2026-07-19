"""p9_b6_depends_on_phase

Revision ID: f4da14ce1be5
Revises: 78b922dc881b
Create Date: 2026-07-07 11:10:09.667436
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4da14ce1be5'
down_revision: Union[str, None] = '78b922dc881b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P9-B6: Task 依赖 + Batch 结构化编号
    op.add_column('task', sa.Column('depends_on', sa.String(length=2000), nullable=True))
    op.add_column('batch', sa.Column('phase', sa.String(length=10), nullable=True))
    op.add_column('batch', sa.Column('batch_number', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('task', 'depends_on')
    op.drop_column('batch', 'batch_number')
    op.drop_column('batch', 'phase')
