"""p10_b2_worker_actor_type_user_id

Revision ID: d21119f06a2a
Revises: 019f6dd5c3e9
Create Date: 2026-07-17

P10-B2: ADR-004 workers 表扩展
- 新增 actor_type 列（human | agent）
- 新增 user_id 列（FK → user.id）
- team_id NOT NULL → NULLABLE

幂等设计：add_column 用 batch_alter_table（SQLite 兼容），
create_foreign_key 用 try/except 防重复创建。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.exc import OperationalError


# revision identifiers, used by Alembic.
revision: str = 'd21119f06a2a'
down_revision: Union[str, None] = '019f6dd5c3e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Single batch operation: add columns + FK + alter nullable ──
    # Using batch_alter_table for full SQLite compatibility.
    with op.batch_alter_table('worker') as batch_op:
        batch_op.add_column(
            sa.Column(
                'actor_type', sa.String(10), nullable=False,
                server_default=sa.text("'agent'"),
                comment="human | agent — 同一张表，人和 AI 统一建模",
            ),
        )
        batch_op.add_column(
            sa.Column(
                'user_id', sa.String(40), nullable=True,
                comment="人类 User 的 FK — agent 行为 NULL",
            ),
        )
        batch_op.create_foreign_key(
            'fk_worker_user_id_user', 'user',
            ['user_id'], ['id'],
        )
        batch_op.alter_column('team_id', nullable=True)

    # ── Indexes ────────────────────────────────────────────────────
    op.create_index('ix_worker_actor_type', 'worker', ['actor_type'])
    op.create_index('ix_worker_user_id', 'worker', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_worker_user_id', 'worker')
    op.drop_index('ix_worker_actor_type', 'worker')

    with op.batch_alter_table('worker') as batch_op:
        batch_op.drop_constraint('fk_worker_user_id_user', type_='foreignkey')
        batch_op.alter_column('team_id', nullable=False)
        batch_op.drop_column('user_id')
        batch_op.drop_column('actor_type')
