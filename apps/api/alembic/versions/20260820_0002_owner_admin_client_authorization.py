"""Allow Firm Owner and Firm Admin to access every same-Firm client.

Revision ID: 20260820_0002
Revises: 20260820_0001
Create Date: 2026-08-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260820_0002"
down_revision: str | None = "20260820_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ASSIGNMENT_ONLY_SCOPE = """
firm_id = NULLIF(current_setting('privexa.firm_id', true), '')::uuid
AND id = NULLIF(current_setting('privexa.client_id', true), '')::uuid
AND EXISTS (
    SELECT 1
    FROM firm_memberships AS membership
    JOIN users AS app_user ON app_user.id = membership.user_id
    JOIN firms AS firm ON firm.id = membership.firm_id
    JOIN client_access_grants AS access_grant
      ON access_grant.firm_id = membership.firm_id
     AND access_grant.membership_id = membership.id
     AND access_grant.client_id = client_workspaces.id
    WHERE membership.id = NULLIF(current_setting('privexa.membership_id', true), '')::uuid
      AND membership.firm_id = client_workspaces.firm_id
      AND membership.user_id = NULLIF(current_setting('privexa.user_id', true), '')::uuid
      AND membership.status = 'ACTIVE'
      AND app_user.status = 'ACTIVE'
      AND firm.status = 'ACTIVE'
      AND access_grant.status = 'ACTIVE'
)
"""

ROLE_AWARE_SCOPE = """
firm_id = NULLIF(current_setting('privexa.firm_id', true), '')::uuid
AND id = NULLIF(current_setting('privexa.client_id', true), '')::uuid
AND EXISTS (
    SELECT 1
    FROM firm_memberships AS membership
    JOIN users AS app_user ON app_user.id = membership.user_id
    JOIN firms AS firm ON firm.id = membership.firm_id
    WHERE membership.id = NULLIF(current_setting('privexa.membership_id', true), '')::uuid
      AND membership.firm_id = client_workspaces.firm_id
      AND membership.user_id = NULLIF(current_setting('privexa.user_id', true), '')::uuid
      AND membership.status = 'ACTIVE'
      AND app_user.status = 'ACTIVE'
      AND firm.status = 'ACTIVE'
      AND (
          membership.role IN ('FIRM_OWNER', 'FIRM_ADMIN')
          OR (
              membership.role IN ('CONSULTANT', 'REVIEWER', 'READ_ONLY')
              AND EXISTS (
                  SELECT 1
                  FROM client_access_grants AS access_grant
                  WHERE access_grant.firm_id = membership.firm_id
                    AND access_grant.membership_id = membership.id
                    AND access_grant.client_id = client_workspaces.id
                    AND access_grant.status = 'ACTIVE'
              )
          )
      )
)
"""


def _replace_client_workspace_policy(scope: str) -> None:
    op.execute("DROP POLICY IF EXISTS client_workspaces_tenant_isolation ON client_workspaces")
    op.execute(
        f"""
        CREATE POLICY client_workspaces_tenant_isolation
        ON client_workspaces
        FOR ALL
        USING ({scope})
        WITH CHECK ({scope})
        """
    )


def upgrade() -> None:
    _replace_client_workspace_policy(ROLE_AWARE_SCOPE)


def downgrade() -> None:
    _replace_client_workspace_policy(ASSIGNMENT_ONLY_SCOPE)
