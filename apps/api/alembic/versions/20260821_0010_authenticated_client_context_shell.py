"""Add authenticated active-client session context.

Revision ID: 20260821_0010
Revises: 20260821_0009
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260821_0010"
down_revision: str | None = "20260821_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    op.create_table(
        "active_client_sessions",
        sa.Column("firm_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active_client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "session_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_active_client_sessions_session_fingerprint_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "active_client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_active_client_sessions_firm_client",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_active_client_sessions_firm_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_active_client_sessions"),
        sa.UniqueConstraint(
            "firm_id",
            "membership_id",
            "session_fingerprint",
            name="uq_active_client_sessions_firm_membership_session",
        ),
    )
    op.create_index(
        "ix_active_client_sessions_firm_membership_active_client",
        "active_client_sessions",
        ["firm_id", "membership_id", "active_client_id"],
        unique=False,
    )

    op.execute("ALTER TABLE active_client_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE active_client_sessions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY active_client_sessions_scoped_select
        ON active_client_sessions
        FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND membership_id = privexa_private.current_context_uuid(
                'privexa.membership_id'
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY active_client_sessions_scoped_insert
        ON active_client_sessions
        FOR INSERT
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND membership_id = privexa_private.current_context_uuid(
                'privexa.membership_id'
            )
            AND active_client_id = privexa_private.validated_client_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY active_client_sessions_scoped_update
        ON active_client_sessions
        FOR UPDATE
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND membership_id = privexa_private.current_context_uuid(
                'privexa.membership_id'
            )
        )
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND membership_id = privexa_private.current_context_uuid(
                'privexa.membership_id'
            )
            AND active_client_id = privexa_private.validated_client_id()
        )
        """
    )

    op.execute(
        """
        CREATE FUNCTION privexa_private.list_authorized_active_clients()
        RETURNS TABLE(client_id uuid, display_name text)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog
        AS $function$
            SELECT client.id, client.name::text
            FROM public.firm_memberships AS membership
            JOIN public.users AS app_user ON app_user.id = membership.user_id
            JOIN public.firms AS firm ON firm.id = membership.firm_id
            JOIN public.client_workspaces AS client ON client.firm_id = firm.id
            WHERE membership.id = privexa_private.current_context_uuid(
                      'privexa.membership_id'
                  )
              AND membership.user_id = privexa_private.current_context_uuid(
                      'privexa.user_id'
                  )
              AND membership.firm_id = privexa_private.current_context_uuid(
                      'privexa.firm_id'
                  )
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
            ORDER BY lower(client.name), client.id
        $function$
        """
    )

    runtime_role = _runtime_role()
    op.execute(
        "REVOKE ALL ON FUNCTION privexa_private.list_authorized_active_clients() FROM PUBLIC"
    )
    op.execute(
        "GRANT EXECUTE ON FUNCTION privexa_private.list_authorized_active_clients() "
        f"TO {runtime_role}"
    )
    op.execute(f"GRANT SELECT, INSERT ON active_client_sessions TO {runtime_role}")
    op.execute(
        f"GRANT UPDATE (active_client_id, updated_at) ON active_client_sessions TO {runtime_role}"
    )


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(
        "REVOKE EXECUTE ON FUNCTION privexa_private.list_authorized_active_clients() "
        f"FROM {runtime_role}"
    )
    op.execute("DROP FUNCTION privexa_private.list_authorized_active_clients()")
    op.drop_index(
        "ix_active_client_sessions_firm_membership_active_client",
        table_name="active_client_sessions",
    )
    op.drop_table("active_client_sessions")
