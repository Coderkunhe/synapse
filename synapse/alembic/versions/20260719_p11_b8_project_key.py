"""p11_b8_project_key

Revision ID: p11b8_001
Revises: ae2fbdb020ba
Create Date: 2026-07-19 12:00:00.000000

P11-B8: Add project_key_hash to project table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'ae2fbdb020ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("project") as ba:
        ba.add_column(sa.Column(
            "project_key_hash", sa.String(255), nullable=True,
            comment="SHA-256 hash of project access key — unguessable credential for Worker discovery (P11-B8)",
        ))
    # Index on project_key_hash for fast lookup
    with op.batch_alter_table("project") as ba:
        ba.create_index("ix_project_project_key_hash", ["project_key_hash"])


def downgrade() -> None:
    with op.batch_alter_table("project") as ba:
        ba.drop_index("ix_project_project_key_hash")
    with op.batch_alter_table("project") as ba:
        ba.drop_column("project_key_hash")
