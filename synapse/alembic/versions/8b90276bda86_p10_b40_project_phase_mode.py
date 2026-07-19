"""p10_b40_project_phase_mode

Revision ID: 8b90276bda86
Revises: a71c07eab1d8
Create Date: 2026-07-18 12:34:45.745101
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b90276bda86'
down_revision: Union[str, None] = 'a71c07eab1d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('project', sa.Column(
        'use_phase_mode', sa.Boolean(),
        nullable=False, server_default=sa.text('0'),
        comment='Phase/Sprint 二级编号模式开关 (P10-B40)',
    ))
    op.add_column('project', sa.Column(
        'current_phase', sa.String(length=200), nullable=True,
        comment='当前 Phase 名称/目标声明 (P10-B40)',
    ))


def downgrade() -> None:
    op.drop_column('project', 'current_phase')
    op.drop_column('project', 'use_phase_mode')
