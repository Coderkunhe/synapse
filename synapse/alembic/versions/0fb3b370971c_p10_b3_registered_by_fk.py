"""p10_b3_registered_by_fk

Revision ID: 0fb3b370971c
Revises: d21119f06a2a
Create Date: 2026-07-17 11:31:59.599000

P10-B3: registered_by FK member→worker + NULLABLE

- 将 registered_by 从 FK→member.id 改为 FK→worker.id
- NOT NULL → NULLABLE（系统自建 Worker 无注册者）
- SQLite 不支持 ALTER FK，使用两段 batch_alter_table：
  1. Block 1: drop column — 彻底消除无名 FK→member + NOT NULL 约束
  2. Block 2: add column — 新建 nullable + 命名 FK→worker
- 旧 member ID 值丢弃（不会存在于 workers 表中）

Why 两段：单段 drop+add 同名在 SQLite batch 模式下会保留无名 FK 残留。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0fb3b370971c'
down_revision: Union[str, None] = 'd21119f06a2a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Block 1: drop old column — kills unnamed FK→member + NOT NULL
    with op.batch_alter_table('worker') as batch_op:
        batch_op.drop_column('registered_by')

    # Block 2: add fresh column with nullable + new named FK→worker
    with op.batch_alter_table('worker') as batch_op:
        batch_op.add_column(
            sa.Column(
                'registered_by', sa.String(40), nullable=True,
                comment="注册此 Agent 的 Worker ID — 通常指向人类 Worker；系统自建为 NULL",
            ),
        )
        batch_op.create_foreign_key(
            'fk_worker_registered_by_worker', 'worker',
            ['registered_by'], ['id'],
        )


def downgrade() -> None:
    # Block 1: drop new column — kills named FK→worker
    with op.batch_alter_table('worker') as batch_op:
        batch_op.drop_constraint('fk_worker_registered_by_worker', type_='foreignkey')
        batch_op.drop_column('registered_by')

    # Block 2: add back NOT NULL + FK→member
    with op.batch_alter_table('worker') as batch_op:
        batch_op.add_column(
            sa.Column('registered_by', sa.String(40), nullable=False),
        )
        batch_op.create_foreign_key(
            'fk_worker_registered_by_member', 'member',
            ['registered_by'], ['id'],
        )
