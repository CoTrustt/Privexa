"""Enforce AI provenance authorization-scope ownership.

Revision ID: 20260822_0016
Revises: 20260822_0015
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0016"
down_revision: str | None = "20260822_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM ai_executions
                    WHERE (authorization_scope = 'CLIENT' AND client_id IS NULL)
                       OR (authorization_scope IN ('FIRM', 'SELF') AND client_id IS NOT NULL)
                ) THEN
                    RAISE EXCEPTION
                        'ai_executions contains rows inconsistent with authorization scope';
                END IF;
            END
            $$
            """
        )
    )
    op.create_check_constraint(
        "ai_execution_authorization_scope_client",
        "ai_executions",
        "(authorization_scope = 'CLIENT' AND client_id IS NOT NULL) OR "
        "(authorization_scope IN ('FIRM', 'SELF') AND client_id IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ai_execution_authorization_scope_client",
        "ai_executions",
        type_="check",
    )
