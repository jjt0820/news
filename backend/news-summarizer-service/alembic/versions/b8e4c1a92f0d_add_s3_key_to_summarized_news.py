"""Add s3_key to summarized_news

Revision ID: b8e4c1a92f0d
Revises: 3ab2009f55a3
Create Date: 2026-05-21 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e4c1a92f0d"
down_revision: Union[str, Sequence[str], None] = "3ab2009f55a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "summarized_news",
        sa.Column("s3_key", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("summarized_news", "s3_key")
