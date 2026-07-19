"""p8_b7_failure_handling

Revision ID: 78b922dc881b
Revises: 9f6999366fe3
Create Date: 2026-07-06 08:40:26.142611
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78b922dc881b'
down_revision: Union[str, None] = '9f6999366fe3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "task",
        sa.Column("failure_reason", sa.String(500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task", "failure_reason")
    op.drop_column("task", "failure_count")
