"""p8_b5_verification_state_machine

Revision ID: 6e52e5989975
Revises: 6d9614573263
Create Date: 2026-07-06 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6e52e5989975'
down_revision: Union[str, None] = '6d9614573263'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P8-B5: redo_count on task — tracks how many times a task has been rejected
    op.add_column('task', sa.Column(
        'redo_count', sa.Integer(), nullable=False, server_default=sa.text('0'),
        comment='Number of times this task has been rejected during verification',
    ))
    # P8-B5: rejection_reason on verification — structured rejection per criterion
    op.add_column('verification', sa.Column(
        'rejection_reason', sa.String(length=2000), nullable=True,
        comment='Reason for rejection, bound to specific criteria',
    ))


def downgrade() -> None:
    op.drop_column('verification', 'rejection_reason')
    op.drop_column('task', 'redo_count')
