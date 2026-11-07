"""claims.origin_key + claims.meta; unique conflict pairs

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("claims", sa.Column("origin_key", sa.String(length=40), nullable=True))
    op.add_column(
        "claims",
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.alter_column("claims", "meta", server_default=None)
    op.create_unique_constraint("uq_claims_origin_key", "claims", ["origin_key"])
    op.create_unique_constraint("uq_conflicts_pair", "conflicts", ["claim_a", "claim_b", "kind"])


def downgrade() -> None:
    op.drop_constraint("uq_conflicts_pair", "conflicts", type_="unique")
    op.drop_constraint("uq_claims_origin_key", "claims", type_="unique")
    op.drop_column("claims", "meta")
    op.drop_column("claims", "origin_key")
