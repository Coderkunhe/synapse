"""p100_b40_rename_agent_to_worker

Revision ID: ec1ce19948b3
Revises: 04f005470ca9
Create Date: 2026-07-15 21:33:06.620038
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ec1ce19948b3'
down_revision: Union[str, None] = '04f005470ca9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Rename table: agent → worker
    op.rename_table("agent", "worker")

    # 2. Rename FK columns: agent_id → worker_id
    # SQLite 3.25+ supports ALTER TABLE RENAME COLUMN
    with op.batch_alter_table("capability") as ba:
        ba.alter_column("agent_id", new_column_name="worker_id")
    with op.batch_alter_table("token_usage") as ba:
        ba.alter_column("agent_id", new_column_name="worker_id")
    with op.batch_alter_table("batch") as ba:
        ba.alter_column("assigned_to", new_column_name="assigned_worker_id")

    # Indexes are preserved on column rename in SQLite,
    # but need to verify batch_alter_table handles this correctly.


def downgrade() -> None:
    # Reverse column renames
    with op.batch_alter_table("batch") as ba:
        ba.alter_column("assigned_worker_id", new_column_name="assigned_to")
    with op.batch_alter_table("token_usage") as ba:
        ba.alter_column("worker_id", new_column_name="agent_id")
    with op.batch_alter_table("capability") as ba:
        ba.alter_column("worker_id", new_column_name="agent_id")

    # Reverse table rename
    op.rename_table("worker", "agent")
