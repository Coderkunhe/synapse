"""p100_b180_add_mention_fk_cascade

Revision ID: p100_b180_mention_cascade
Revises: p17_b12_mention_join
Create Date: 2026-10-12

P100-B180 (PFL-276): 给 task_worker_conversation_mention 两处 FK 补 ON DELETE CASCADE。

mention 行是「worker X 在 message Y 被 @」的派生索引行 —— worker 或 message 删除时，
mention 行应随之删除。此前 P17-B12 建的关联表两处 FK（conversation_id / worker_id）都
只写了 ForeignKeyConstraint 未加 ondelete，删 worker/message 会被 mention 行 FK 阻断，
而 mention 行无删除 API，形成无法清理的死角（P17-B16 e2e afterAll 删临时 worker 报 500
FOREIGN KEY constraint failed）。

SQLite 不支持 ALTER 已存在的 FK 约束 → 跨方言统一走「建新表 → 拷贝数据 → 删旧表 →
改名」，保留既有 mention 行。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p100_b180_mention_cascade'
down_revision: Union[str, None] = 'p17_b12_mention_join'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _recreate_table(*, ondelete: str | None) -> None:
    """建临时表 → 拷贝数据 → 删旧表 → 改名 → 重建索引（跨方言一致）。"""
    tmp = "task_worker_conversation_mention__migrate"

    op.create_table(
        tmp,
        sa.Column("id", sa.String(40), nullable=False),
        sa.Column("conversation_id", sa.String(40), nullable=False),
        sa.Column("worker_id", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["task_worker_conversation.id"],
            ondelete=ondelete,
        ),
        sa.ForeignKeyConstraint(["worker_id"], ["worker.id"], ondelete=ondelete),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("conversation_id", "worker_id", name="uq_mention_conv_worker"),
    )
    op.execute(
        f"INSERT INTO {tmp} (id, conversation_id, worker_id) "
        "SELECT id, conversation_id, worker_id FROM task_worker_conversation_mention"
    )
    op.drop_table("task_worker_conversation_mention")
    op.rename_table(tmp, "task_worker_conversation_mention")
    op.create_index(
        "ix_task_worker_conversation_mention_conversation_id",
        "task_worker_conversation_mention",
        ["conversation_id"],
    )
    op.create_index(
        "ix_task_worker_conversation_mention_worker_id",
        "task_worker_conversation_mention",
        ["worker_id"],
    )


def upgrade() -> None:
    _recreate_table(ondelete="CASCADE")


def downgrade() -> None:
    _recreate_table(ondelete=None)
