"""Bind Stytch B2B identities to existing Privexa tenant records.

Revision ID: 20260820_0003
Revises: 20260820_0002
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260820_0003"
down_revision: str | None = "20260820_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "firms",
        sa.Column("stytch_organization_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_firms_stytch_organization_id",
        "firms",
        ["stytch_organization_id"],
        unique=True,
        postgresql_where=sa.text("stytch_organization_id IS NOT NULL"),
    )

    op.add_column(
        "firm_memberships",
        sa.Column("stytch_member_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_firm_memberships_stytch_member_id",
        "firm_memberships",
        ["stytch_member_id"],
        unique=True,
        postgresql_where=sa.text("stytch_member_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_firm_memberships_stytch_member_id",
        table_name="firm_memberships",
    )
    op.drop_column("firm_memberships", "stytch_member_id")

    op.drop_index("uq_firms_stytch_organization_id", table_name="firms")
    op.drop_column("firms", "stytch_organization_id")
