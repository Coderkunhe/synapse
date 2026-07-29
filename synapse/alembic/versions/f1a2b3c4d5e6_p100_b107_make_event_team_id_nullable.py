"""p100_b107_make_event_team_id_nullable

Revision ID: f1a2b3c4d5e6
Revises: f09a786c4238
Create Date: 2026-07-29 17:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'f09a786c4238'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P100-B107: Event.team_id → nullable for system-level events
    with op.batch_alter_table('event') as batch_op:
        batch_op.alter_column('team_id', nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('event') as batch_op:
        batch_op.alter_column('team_id', nullable=False)
