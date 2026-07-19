"""p10_b1_users_and_auth_methods

Revision ID: 019f6dd5c3e9
Revises: ec1ce19948b3
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '019f6dd5c3e9'
down_revision: Union[str, None] = 'ec1ce19948b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user 表 ────────────────────────────────────────────────
    op.create_table(
        'user',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('email', sa.String(255), nullable=True, unique=True, index=True),
        sa.Column('password_hash', sa.String(255), nullable=True,
                  comment='bcrypt hash — NULL for OAuth-only users'),
        sa.Column('display_name', sa.String(100), nullable=False),
        sa.Column('avatar_url', sa.String(2048), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False,
                  server_default=sa.text('1'),
                  comment='软禁用标记 — False = 账号已停用'),
        # AuditMixin fields
        sa.Column('is_disabled', sa.Boolean(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('create_user_id', sa.String(40), nullable=False,
                  server_default=sa.text("'system'")),
        sa.Column('last_update_user_id', sa.String(40), nullable=True),
        sa.Column('remark', sa.String(2000), nullable=True),
        sa.Column('version_no', sa.Integer(), nullable=False,
                  server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
    )

    # ── user_auth_method 表 ─────────────────────────────────────
    op.create_table(
        'user_auth_method',
        sa.Column('id', sa.String(40), primary_key=True),
        sa.Column('user_id', sa.String(40), sa.ForeignKey('user.id'),
                  nullable=False, index=True),
        sa.Column('provider', sa.String(20), nullable=False,
                  comment='认证提供商: github | google | email'),
        sa.Column('subject', sa.String(255), nullable=False,
                  comment='provider 侧的用户标识'),
        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        # AuditMixin fields
        sa.Column('is_disabled', sa.Boolean(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('create_user_id', sa.String(40), nullable=False,
                  server_default=sa.text("'system'")),
        sa.Column('last_update_user_id', sa.String(40), nullable=True),
        sa.Column('remark', sa.String(2000), nullable=True),
        sa.Column('version_no', sa.Integer(), nullable=False,
                  server_default=sa.text('1')),
        sa.Column('updated_at', sa.DateTime(), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('provider', 'subject',
                            name='uq_user_auth_method_provider_subject'),
    )


def downgrade() -> None:
    op.drop_table('user_auth_method')
    op.drop_table('user')
