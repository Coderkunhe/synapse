"""p11_b46_add_capability_fields

Revision ID: b46c4p4b1l1ty
Revises: a1b2c3d4e5f6
Create Date: 2026-07-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b46c4p4b1l1ty'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add capability_exec fields to authorization_requests table."""
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()}

    if 'authorization_requests' not in tables:
        return  # table not created yet — skip

    cols = {row[1] for row in conn.execute(
        sa.text("PRAGMA table_info('authorization_requests')")
    ).fetchall()}

    if 'capability_id' not in cols:
        op.add_column(
            'authorization_requests',
            sa.Column('capability_id', sa.String(100), nullable=True),
        )

    if 'outcome' not in cols:
        op.add_column(
            'authorization_requests',
            sa.Column('outcome', sa.String(20), nullable=True),
        )

    if 'exit_code' not in cols:
        op.add_column(
            'authorization_requests',
            sa.Column('exit_code', sa.Integer(), nullable=True),
        )

    if 'duration_ms' not in cols:
        op.add_column(
            'authorization_requests',
            sa.Column('duration_ms', sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    """Remove capability_exec fields."""
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()}
    if 'authorization_requests' not in tables:
        return

    op.drop_column('authorization_requests', 'duration_ms')
    op.drop_column('authorization_requests', 'exit_code')
    op.drop_column('authorization_requests', 'outcome')
    op.drop_column('authorization_requests', 'capability_id')
