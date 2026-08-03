"""p11_b117_add_proposal_status_to_message

Revision ID: b117_proposal_status
Revises: f1a2b3c4d5e6
Create Date: 2026-08-03T09:24:47.503181
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b117_proposal_status'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('task_worker_conversation', sa.Column('proposal_status', sa.String(length=20), nullable=True))
    op.create_index('ix_task_worker_conversation_proposal_status', 'task_worker_conversation', ['proposal_status'])


def downgrade() -> None:
    op.drop_index('ix_task_worker_conversation_proposal_status', 'task_worker_conversation')
    op.drop_column('task_worker_conversation', 'proposal_status')
