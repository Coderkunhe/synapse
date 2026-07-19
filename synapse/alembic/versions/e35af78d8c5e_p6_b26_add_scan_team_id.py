"""p6_b26_add_scan_team_id

Revision ID: e35af78d8c5e
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-05 04:11:23.003034
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e35af78d8c5e'
down_revision: Union[str, None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent — check table exists + team_id column exists before adding
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()}

    if 'scan_result' not in tables:
        return  # table not created yet — skip (scan_result added in later migration)

    scan_cols = {row[1] for row in conn.execute(
        sa.text("PRAGMA table_info('scan_result')")
    ).fetchall()}

    if 'team_id' not in scan_cols:
        op.add_column(
            'scan_result',
            sa.Column('team_id', sa.String(40), nullable=True),
        )
        op.create_index(
            op.f('ix_scan_result_team_id'), 'scan_result', ['team_id'], unique=False
        )


def downgrade() -> None:
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(
        sa.text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()}
    if 'scan_result' not in tables:
        return
    op.drop_index(op.f('ix_scan_result_team_id'), table_name='scan_result')
    op.drop_column('scan_result', 'team_id')
