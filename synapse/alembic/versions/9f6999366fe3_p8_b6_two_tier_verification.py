"""p8_b6_two_tier_verification

Revision ID: 9f6999366fe3
Revises: 6e52e5989975
Create Date: 2026-07-06 01:31:35.693213
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f6999366fe3'
down_revision: Union[str, None] = '6e52e5989975'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P8-B6: Two-tier verification — review_flag + auto_approved
    op.add_column(
        'verification',
        sa.Column('review_flag', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )
    op.add_column(
        'verification',
        sa.Column('auto_approved', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )


def downgrade() -> None:
    op.drop_column('verification', 'auto_approved')
    op.drop_column('verification', 'review_flag')
