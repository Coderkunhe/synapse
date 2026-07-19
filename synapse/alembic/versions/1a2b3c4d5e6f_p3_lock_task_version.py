"""P3 Lock: add version column to task for optimistic concurrency control.

Revision ID: 1a2b3c4d5e6f
Revises: b3723cc98c7a
Create Date: 2026-07-04
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, None] = 'b3723cc98c7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('task') as batch_op:
        batch_op.add_column(
            sa.Column('version', sa.Integer(), nullable=False, server_default='1')
        )


def downgrade() -> None:
    with op.batch_alter_table('task') as batch_op:
        batch_op.drop_column('version')
