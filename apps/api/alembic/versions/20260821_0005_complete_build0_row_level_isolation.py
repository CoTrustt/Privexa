"""Complete Build 0 PostgreSQL row-level tenant isolation.

Revision ID: 20260821_0005
Revises: 20260820_0004
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "20260821_0005"
down_revision: str | None = "20260820_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECTED_TABLES = (
    "firms",
    "users",
    "firm_memberships",
    "client_workspaces",
    "client_access_grants",
)

ROLE_AWARE_CLIENT_SCOPE = """
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


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def _create_security_functions() -> None:
    op.execute("CREATE SCHEMA privexa_private")
    op.execute("REVOKE ALL ON SCHEMA privexa_private FROM PUBLIC")

    op.execute(
        """
        CREATE FUNCTION privexa_private.current_context_uuid(setting_name text)
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        SECURITY INVOKER
        SET search_path = pg_catalog
        AS $function$
        DECLARE
            raw_value text;
        BEGIN
            raw_value := current_setting(setting_name, true);
            IF raw_value IS NULL OR raw_value = '' THEN
                RETURN NULL;
            END IF;
            RETURN raw_value::uuid;
        EXCEPTION
            WHEN invalid_text_representation THEN
                RETURN NULL;
        END;
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION privexa_private.resolve_authenticated_identity(
            requested_stytch_member_id text,
            requested_stytch_organization_id text
        )
        RETURNS TABLE (
            user_id uuid,
            membership_id uuid,
            firm_id uuid,
            role text,
            user_status text,
            membership_status text,
            firm_status text,
            firm_name text,
            display_name text
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT
                app_user.id,
                membership.id,
                firm.id,
                membership.role::text,
                app_user.status::text,
                membership.status::text,
                firm.status::text,
                firm.name::text,
                app_user.display_name::text
            FROM public.firm_memberships AS membership
            JOIN public.users AS app_user ON app_user.id = membership.user_id
            JOIN public.firms AS firm ON firm.id = membership.firm_id
            WHERE membership.stytch_member_id = requested_stytch_member_id
              AND firm.stytch_organization_id = requested_stytch_organization_id
            LIMIT 1
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION privexa_private.validated_firm_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT firm.id
            FROM public.firm_memberships AS membership
            JOIN public.users AS app_user ON app_user.id = membership.user_id
            JOIN public.firms AS firm ON firm.id = membership.firm_id
            WHERE membership.id = privexa_private.current_context_uuid(
                      'privexa.membership_id'
                  )
              AND membership.user_id = privexa_private.current_context_uuid('privexa.user_id')
              AND membership.firm_id = privexa_private.current_context_uuid('privexa.firm_id')
              AND membership.status = 'ACTIVE'
              AND app_user.status = 'ACTIVE'
              AND firm.status = 'ACTIVE'
            LIMIT 1
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION privexa_private.resolve_current_membership(
            requested_user_id uuid,
            requested_membership_id uuid,
            requested_firm_id uuid
        )
        RETURNS TABLE (
            role text,
            user_status text,
            membership_status text,
            firm_status text
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT
                membership.role::text,
                app_user.status::text,
                membership.status::text,
                firm.status::text
            FROM public.firm_memberships AS membership
            JOIN public.users AS app_user ON app_user.id = membership.user_id
            JOIN public.firms AS firm ON firm.id = membership.firm_id
            WHERE membership.id = requested_membership_id
              AND membership.user_id = requested_user_id
              AND membership.firm_id = requested_firm_id
              AND requested_membership_id = privexa_private.current_context_uuid(
                      'privexa.membership_id'
                  )
              AND requested_user_id = privexa_private.current_context_uuid('privexa.user_id')
              AND requested_firm_id = privexa_private.current_context_uuid('privexa.firm_id')
            LIMIT 1
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION privexa_private.validated_role()
        RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT membership.role::text
            FROM public.firm_memberships AS membership
            JOIN public.users AS app_user ON app_user.id = membership.user_id
            JOIN public.firms AS firm ON firm.id = membership.firm_id
            WHERE membership.id = privexa_private.current_context_uuid(
                      'privexa.membership_id'
                  )
              AND membership.user_id = privexa_private.current_context_uuid('privexa.user_id')
              AND membership.firm_id = privexa_private.current_context_uuid('privexa.firm_id')
              AND membership.status = 'ACTIVE'
              AND app_user.status = 'ACTIVE'
              AND firm.status = 'ACTIVE'
            LIMIT 1
        $function$
        """
    )
    op.execute(
        """
        CREATE FUNCTION privexa_private.validated_client_id()
        RETURNS uuid
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT client.id
            FROM public.firm_memberships AS membership
            JOIN public.users AS app_user ON app_user.id = membership.user_id
            JOIN public.firms AS firm ON firm.id = membership.firm_id
            JOIN public.client_workspaces AS client ON client.firm_id = membership.firm_id
            WHERE membership.id = privexa_private.current_context_uuid(
                      'privexa.membership_id'
                  )
              AND membership.user_id = privexa_private.current_context_uuid('privexa.user_id')
              AND membership.firm_id = privexa_private.current_context_uuid('privexa.firm_id')
              AND client.id = privexa_private.current_context_uuid('privexa.client_id')
              AND membership.status = 'ACTIVE'
              AND app_user.status = 'ACTIVE'
              AND firm.status = 'ACTIVE'
              AND client.status = 'ACTIVE'
              AND (
                  membership.role IN ('FIRM_OWNER', 'FIRM_ADMIN')
                  OR (
                      membership.role IN ('CONSULTANT', 'REVIEWER', 'READ_ONLY')
                      AND EXISTS (
                          SELECT 1
                          FROM public.client_access_grants AS access_grant
                          WHERE access_grant.firm_id = membership.firm_id
                            AND access_grant.membership_id = membership.id
                            AND access_grant.client_id = client.id
                            AND access_grant.status = 'ACTIVE'
                      )
                  )
              )
            LIMIT 1
        $function$
        """
    )

    runtime_role = _runtime_role()
    op.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA privexa_private FROM PUBLIC")
    op.execute(f"GRANT USAGE ON SCHEMA privexa_private TO {runtime_role}")
    op.execute(f"GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA privexa_private TO {runtime_role}")


def _enable_rls_and_create_policies() -> None:
    op.execute("DROP POLICY IF EXISTS client_workspaces_tenant_isolation ON client_workspaces")
    op.execute("DROP POLICY IF EXISTS client_access_grants_scoped_select ON client_access_grants")

    for table_name in PROTECTED_TABLES:
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY firms_scoped_select
        ON firms
        FOR SELECT
        USING (id = privexa_private.validated_firm_id())
        """
    )
    op.execute(
        """
        CREATE POLICY firms_scoped_update
        ON firms
        FOR UPDATE
        USING (
            id = privexa_private.validated_firm_id()
            AND privexa_private.validated_role() IN ('FIRM_OWNER', 'FIRM_ADMIN')
        )
        WITH CHECK (id = privexa_private.validated_firm_id())
        """
    )
    op.execute(
        """
        CREATE POLICY users_firm_scoped_select
        ON users
        FOR SELECT
        USING (
            EXISTS (
                SELECT 1
                FROM firm_memberships AS membership
                WHERE membership.user_id = users.id
                  AND membership.firm_id = privexa_private.validated_firm_id()
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY users_self_update
        ON users
        FOR UPDATE
        USING (
            id = privexa_private.current_context_uuid('privexa.user_id')
            AND privexa_private.validated_firm_id() IS NOT NULL
        )
        WITH CHECK (
            id = privexa_private.current_context_uuid('privexa.user_id')
            AND privexa_private.validated_firm_id() IS NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE POLICY firm_memberships_firm_scoped_select
        ON firm_memberships
        FOR SELECT
        USING (firm_id = privexa_private.validated_firm_id())
        """
    )
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
    op.execute(
        """
        CREATE POLICY client_workspaces_scoped_insert
        ON client_workspaces
        FOR INSERT
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND id = privexa_private.current_context_uuid('privexa.client_id')
            AND privexa_private.validated_role() IN ('FIRM_OWNER', 'FIRM_ADMIN')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY client_workspaces_scoped_update
        ON client_workspaces
        FOR UPDATE
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND id = privexa_private.validated_client_id()
            AND privexa_private.validated_role() IN ('FIRM_OWNER', 'FIRM_ADMIN')
        )
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND id = privexa_private.current_context_uuid('privexa.client_id')
            AND privexa_private.validated_role() IN ('FIRM_OWNER', 'FIRM_ADMIN')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY client_access_grants_scoped_select
        ON client_access_grants
        FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
            AND membership_id = privexa_private.current_context_uuid('privexa.membership_id')
        )
        """
    )


def upgrade() -> None:
    _create_security_functions()
    _enable_rls_and_create_policies()

    runtime_role = _runtime_role()
    tables = ", ".join(PROTECTED_TABLES)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {runtime_role}")


def downgrade() -> None:
    for policy_name, table_name in (
        ("client_access_grants_scoped_select", "client_access_grants"),
        ("client_workspaces_scoped_update", "client_workspaces"),
        ("client_workspaces_scoped_insert", "client_workspaces"),
        ("client_workspaces_scoped_select", "client_workspaces"),
        ("firm_memberships_firm_scoped_select", "firm_memberships"),
        ("users_self_update", "users"),
        ("users_firm_scoped_select", "users"),
        ("firms_scoped_update", "firms"),
        ("firms_scoped_select", "firms"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}")

    for table_name in ("firm_memberships", "users", "firms"):
        op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY client_workspaces_tenant_isolation
        ON client_workspaces
        FOR ALL
        USING ({ROLE_AWARE_CLIENT_SCOPE})
        WITH CHECK ({ROLE_AWARE_CLIENT_SCOPE})
        """
    )
    op.execute(
        f"""
        CREATE POLICY client_access_grants_scoped_select
        ON client_access_grants
        FOR SELECT
        USING ({CLIENT_ACCESS_SCOPE})
        """
    )

    op.execute("DROP FUNCTION privexa_private.validated_client_id()")
    op.execute("DROP FUNCTION privexa_private.validated_role()")
    op.execute("DROP FUNCTION privexa_private.resolve_current_membership(uuid, uuid, uuid)")
    op.execute("DROP FUNCTION privexa_private.validated_firm_id()")
    op.execute("DROP FUNCTION privexa_private.resolve_authenticated_identity(text, text)")
    op.execute("DROP FUNCTION privexa_private.current_context_uuid(text)")
    op.execute("DROP SCHEMA privexa_private")
