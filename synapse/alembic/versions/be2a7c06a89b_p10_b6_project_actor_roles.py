"""p10_b6_project_actor_roles

Revision ID: be2a7c06a89b
Revises: 0d369923c010
Create Date: 2026-07-17 13:08:36.929346

P10-B6: project_actor_roles 表创建

ADR-004 四实体架构第四张新表 —— Project → Worker 权限映射。
替代旧 ``member.role`` 的全局权限，Project 是权限的真正主体。

表结构：
  - id: PK, 40 chars
  - project_id: FK → project.id
  - worker_id: FK → worker.id
  - role: 标签（"orchestrator" | "builder" | "steward" 等），默认 "member"
  - UNIQUE (project_id, worker_id) — 一个 Worker 在一个 Project 里只有一条角色记录
  - 继承 AuditMixin 全量审计字段

本批只建表结构，不做数据迁移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be2a7c06a89b'
down_revision: Union[str, None] = '0d369923c010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_actor_roles",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("project_id", sa.String(40), sa.ForeignKey("project.id"), nullable=False, index=True,
                  comment="所属 Project"),
        sa.Column("worker_id", sa.String(40), sa.ForeignKey("worker.id"), nullable=False, index=True,
                  comment="Project 中的 Worker（人或 AI）"),
        sa.Column("role", sa.String(20), nullable=False, server_default="member",
                  comment="Project 内角色标签 — orchestrator / builder / steward 等"),
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
        sa.UniqueConstraint("project_id", "worker_id", name="uq_project_actor_roles_project_worker"),
    )


def downgrade() -> None:
    op.drop_table("project_actor_roles")
