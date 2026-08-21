"""Restrict client access grants to scoped reads at the runtime boundary.

Revision ID: 20260820_0004
Revises: 20260820_0003
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_0004"
down_revision: str | None = "20260820_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CLIENT_ACCESS_SCOPE = """
firm_id = NULLIF(current_setting('privexa.firm_id', true), '')::uuid
AND client_id = NULLIF(current_setting('privexa.client_id', true), '')::uuid
AND membership_id = NULLIF(current_setting('privexa.membership_id', true), '')::uuid
AND EXISTS (
    SELECT 1
    FROM firm_memberships AS membership
    JOIN users AS app_user ON app_user.id = membership.user_id
    JOIN firms AS firm ON firm.id = membership.firm_id
    WHERE membership.id = client_access_grants.membership_id
      AND membership.firm_id = client_access_grants.firm_id
      AND membership.user_id = NULLIF(current_setting('privexa.user_id', true), '')::uuid
      AND membership.status = 'ACTIVE'
      AND app_user.status = 'ACTIVE'
      AND firm.status = 'ACTIVE'
)
"""


def upgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS client_access_grants_tenant_isolation ON client_access_grants"
    )
    op.execute(
        f"""
        CREATE POLICY client_access_grants_scoped_select
        ON client_access_grants
        FOR SELECT
        USING ({CLIENT_ACCESS_SCOPE})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS client_access_grants_scoped_select ON client_access_grants")
    op.execute(
        f"""
        CREATE POLICY client_access_grants_tenant_isolation
        ON client_access_grants
        FOR ALL
        USING ({CLIENT_ACCESS_SCOPE})
        WITH CHECK ({CLIENT_ACCESS_SCOPE})
        """
    )
