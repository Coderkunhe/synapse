"""p17_b12_add_conversation_mention_join_table

Revision ID: p17_b12_mention_join
Revises: b117_proposal_status
Create Date: 2026-10-02

P17-B12: 新增 task_worker_conversation_mention 关联表——可索引的 worker mention 查询。
mentions_json 存 name 供展示；本表存解析后的 worker_id 供查询。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p17_b12_mention_join'
down_revision: Union[str, None] = 'b117_proposal_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'task_worker_conversation_mention',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('conversation_id', sa.String(length=40), nullable=False),
        sa.Column('worker_id', sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(['conversation_id'], ['task_worker_conversation.id'], ),
        sa.ForeignKeyConstraint(['worker_id'], ['worker.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('conversation_id', 'worker_id', name='uq_mention_conv_worker'),
    )
    op.create_index('ix_task_worker_conversation_mention_conversation_id', 'task_worker_conversation_mention', ['conversation_id'])
    op.create_index('ix_task_worker_conversation_mention_worker_id', 'task_worker_conversation_mention', ['worker_id'])


def downgrade() -> None:
    op.drop_index('ix_task_worker_conversation_mention_worker_id', table_name='task_worker_conversation_mention')
    op.drop_index('ix_task_worker_conversation_mention_conversation_id', table_name='task_worker_conversation_mention')
    op.drop_table('task_worker_conversation_mention')
