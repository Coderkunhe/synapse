"""p10_b5_team_members

Revision ID: 0d369923c010
Revises: 25ddf0eabcac
Create Date: 2026-07-17 04:52:06.754258

P10-B5: team_members 表创建

ADR-004 四实体架构第三张新表 —— Team → Worker 可选多对多映射。
替代旧 ``member`` 表的团队归属功能。

表结构：
  - id: PK, 40 chars
  - team_id: FK → team.id
  - worker_id: FK → worker.id
  - role: 标签（"lead" | "member"），默认 "member"
  - notes: 可选备注（≤2000 chars）
  - UNIQUE (team_id, worker_id) — 一个 Worker 在一个 Team 里只有一条 membership
  - 继承 AuditMixin 全量审计字段

本批只建表结构，不做数据迁移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d369923c010'
down_revision: Union[str, None] = '25ddf0eabcac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "team_members",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("team_id", sa.String(40), sa.ForeignKey("team.id"), nullable=False, index=True,
                  comment="所属 Team"),
        sa.Column("worker_id", sa.String(40), sa.ForeignKey("worker.id"), nullable=False, index=True,
                  comment="Team 中的 Worker（人或 AI）"),
        sa.Column("role", sa.String(20), nullable=False, server_default="member",
                  comment="Team 内角色标签 — lead / member 等"),
        sa.Column("notes", sa.String(2000), nullable=True,
                  comment="备注（如加入原因、特殊说明）"),
        # AuditMixin fields
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default=sa.text("0"),
                  comment="软删除/禁用标记"),
        sa.Column("create_user_id", sa.String(40), nullable=False, server_default=sa.text("'system'"),
                  comment="创建者 ID（member_id 或 worker_id）"),
        sa.Column("last_update_user_id", sa.String(40), nullable=True,
                  comment="最后更新者 ID"),
        sa.Column("remark", sa.String(2000), nullable=True,
                  comment="备注/说明"),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default=sa.text("1"),
                  comment="乐观锁版本号"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
                  comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now(),
                  comment="最后更新时间"),
        sa.UniqueConstraint("team_id", "worker_id", name="uq_team_members_team_worker"),
    )


def downgrade() -> None:
    op.drop_table("team_members")
