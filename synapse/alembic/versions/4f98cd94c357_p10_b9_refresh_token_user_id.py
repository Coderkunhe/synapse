"""p10_b9_refresh_token_user_id

Revision ID: 4f98cd94c357
Revises: 019f6ec74577
Create Date: 2026-07-17 15:10:36.437651
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f98cd94c357'
down_revision: Union[str, None] = '019f6ec74577'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── refresh_token: +user_id FK for email/password auth ────────────────
    # SQLite batch mode handles the entire table recreation for ALTER operations
    # that SQLite doesn't natively support (FK constraints, nullable changes).
    with op.batch_alter_table('refresh_token') as batch_op:
        batch_op.add_column(
            sa.Column(
                'user_id', sa.String(length=40), nullable=True,
                comment='P10-B9: FK to User for email/password auth — NULL for legacy OAuth',
            ),
        )
        batch_op.create_index(
            op.f('ix_refresh_token_user_id'), ['user_id'], unique=False,
        )
        batch_op.create_foreign_key(
            'fk_refresh_token_user_id', 'user', ['user_id'], ['id'],
        )
        # member_id → nullable to support new User-based auth path
        batch_op.alter_column('member_id', existing_type=sa.VARCHAR(40), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('refresh_token') as batch_op:
        batch_op.drop_constraint('fk_refresh_token_user_id', type_='foreignkey')
        batch_op.drop_index(op.f('ix_refresh_token_user_id'))
        batch_op.alter_column('member_id', existing_type=sa.VARCHAR(40), nullable=False)
        batch_op.drop_column('user_id')
