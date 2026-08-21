"""Allow an authorized client creation to return its inserted row.

Revision ID: 20260821_0006
Revises: 20260821_0005
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260821_0006"
down_revision: str | None = "20260821_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP POLICY client_workspaces_scoped_select ON client_workspaces")
    op.execute(
        """
        CREATE POLICY client_workspaces_scoped_select
        ON client_workspaces
        FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND (
                id = privexa_private.validated_client_id()
                OR (
                    id = privexa_private.current_context_uuid('privexa.client_id')
                    AND status = 'ACTIVE'
                    AND privexa_private.validated_role() IN ('FIRM_OWNER', 'FIRM_ADMIN')
                )
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY client_workspaces_scoped_select ON client_workspaces")
    op.execute(
        """
        CREATE POLICY client_workspaces_scoped_select
        ON client_workspaces
        FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND id = privexa_private.validated_client_id()
        )
        """
    )
