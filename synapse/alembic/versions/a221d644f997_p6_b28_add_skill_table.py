"""p6_b28_add_skill_table

Revision ID: a221d644f997
Revises: e35af78d8c5e
Create Date: 2026-07-05 05:02:08.614925
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a221d644f997'
down_revision: Union[str, None] = 'e35af78d8c5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent — table may already exist from prior run
    try:
        op.create_table('skill',
        sa.Column('id', sa.String(length=40), nullable=False),
        sa.Column('team_id', sa.String(length=40), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('version', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('template_md', sa.Text(), nullable=False),
        sa.Column('protocol_spec', sa.String(length=4000), nullable=True),
        sa.Column('scan_rule_ids', sa.String(length=2000), nullable=True),
        sa.Column('metadata', sa.String(length=4000), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['team.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_skill_status'), 'skill', ['status'], unique=False)
        op.create_index(op.f('ix_skill_team_id'), 'skill', ['team_id'], unique=False)
    except sa.exc.OperationalError:
        pass


def downgrade() -> None:
    op.drop_index(op.f('ix_skill_team_id'), table_name='skill')
    op.drop_index(op.f('ix_skill_status'), table_name='skill')
    op.drop_table('skill')
