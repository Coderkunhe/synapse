"""p10_b16_db_wide_columns

Revision ID: f04cdc7a20f7
Revises: 7f9de47243da
Create Date: 2026-07-17 19:04:13.615436
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f04cdc7a20f7'
down_revision: Union[str, None] = '7f9de47243da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # P10-B16: DB 宽列 — 为议题 3（授权管道）和议题 7（通知）预留字段
    # SQLite ALTER TABLE via batch_alter_table for column additions

    # 1. user.is_super_admin — 超级管理员标记（议题 3 授权管道需要）
    with op.batch_alter_table("user") as ba:
        ba.add_column(sa.Column(
            "is_super_admin", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="超级管理员标记 — True = 可管理所有 Project 和 User",
        ))

    # 2. user.force_password_change — 首次登录强制改密（管理员创建用户后使用）
    with op.batch_alter_table("user") as ba:
        ba.add_column(sa.Column(
            "force_password_change", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="强制密码修改标记 — True = 下次登录必须改密",
        ))

    # 3. password_reset_token.created_by_admin — 区分管理员重置 vs 用户自主重置
    with op.batch_alter_table("password_reset_token") as ba:
        ba.add_column(sa.Column(
            "created_by_admin", sa.Boolean(), nullable=False, server_default=sa.false(),
            comment="管理员创建的重置令牌 — True = 由管理员触发",
        ))


def downgrade() -> None:
    with op.batch_alter_table("password_reset_token") as ba:
        ba.drop_column("created_by_admin")
    with op.batch_alter_table("user") as ba:
        ba.drop_column("force_password_change")
    with op.batch_alter_table("user") as ba:
        ba.drop_column("is_super_admin")
