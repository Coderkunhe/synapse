"""P10-B8: worker.api_key_hash NULLABLE — human workers use JWT, not API keys

Revision ID: 019f6ec74577
Revises: be2a7c06a89b
Create Date: 2026-07-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "019f6ec74577"
down_revision: Union[str, None] = "be2a7c06a89b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "worker",
        "api_key_hash",
        existing_type=sa.String(255),
        nullable=True,
        existing_server_default=None,
        existing_nullable=False,
    )


def downgrade() -> None:
    # Replace NULL api_key_hash with empty string before reverting to NOT NULL
    op.execute("UPDATE worker SET api_key_hash = '' WHERE api_key_hash IS NULL")
    op.alter_column(
        "worker",
        "api_key_hash",
        existing_type=sa.String(255),
        nullable=False,
        existing_server_default=None,
        existing_nullable=True,
    )
