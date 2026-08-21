"""Create the tenant and client domain foundation.

Revision ID: 20260820_0001
Revises: None
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260820_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)

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

CLIENT_WORKSPACE_SCOPE = """
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


def upgrade() -> None:
    op.create_table(
        "firms",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "SUSPENDED",
                "ARCHIVED",
                name="firm_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("archived_at", TIMESTAMPTZ, nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')",
            name="firm_status",
        ),
        sa.CheckConstraint(
            "(status = 'ARCHIVED' AND archived_at IS NOT NULL) OR "
            "(status <> 'ARCHIVED' AND archived_at IS NULL)",
            name="archived_status_matches_timestamp",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_firms"),
    )

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "DISABLED",
                name="user_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name="email_is_normalized"),
        sa.CheckConstraint(
            "length(trim(email)) > 3",
            name="email_is_not_blank",
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="user_status"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "client_workspaces",
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "INACTIVE",
                "ARCHIVED",
                name="client_workspace_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column("archived_at", TIMESTAMPTZ, nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')",
            name="client_workspace_status",
        ),
        sa.CheckConstraint(
            "(status = 'ARCHIVED' AND archived_at IS NOT NULL) OR "
            "(status <> 'ARCHIVED' AND archived_at IS NULL)",
            name="archived_status_matches_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id"],
            ["firms.id"],
            name="fk_client_workspaces_firm_id_firms",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_client_workspaces"),
        sa.UniqueConstraint(
            "firm_id",
            "id",
            name="uq_client_workspaces_firm_id_id",
        ),
    )
    op.create_index(
        "ix_client_workspaces_firm_id_status",
        "client_workspaces",
        ["firm_id", "status"],
        unique=False,
    )

    op.create_table(
        "firm_memberships",
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "FIRM_OWNER",
                "FIRM_ADMIN",
                "CONSULTANT",
                "REVIEWER",
                "READ_ONLY",
                name="firm_role",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "SUSPENDED",
                "REVOKED",
                name="membership_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "joined_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("revoked_at", TIMESTAMPTZ, nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('FIRM_OWNER', 'FIRM_ADMIN', 'CONSULTANT', 'REVIEWER', 'READ_ONLY')",
            name="firm_role",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="membership_status",
        ),
        sa.CheckConstraint(
            "(status = 'REVOKED' AND revoked_at IS NOT NULL) OR "
            "(status <> 'REVOKED' AND revoked_at IS NULL)",
            name="revoked_status_matches_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id"],
            ["firms.id"],
            name="fk_firm_memberships_firm_id_firms",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_firm_memberships_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_firm_memberships"),
        sa.UniqueConstraint("firm_id", "id", name="uq_firm_memberships_firm_id_id"),
        sa.UniqueConstraint(
            "firm_id",
            "user_id",
            name="uq_firm_memberships_firm_id_user_id",
        ),
    )
    op.create_index(
        "ix_firm_memberships_firm_id_status_role",
        "firm_memberships",
        ["firm_id", "status", "role"],
        unique=False,
    )
    op.create_index(
        "ix_firm_memberships_user_id_status",
        "firm_memberships",
        ["user_id", "status"],
        unique=False,
    )

    op.create_table(
        "client_access_grants",
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ACTIVE",
                "REVOKED",
                name="client_access_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "granted_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("revoked_at", TIMESTAMPTZ, nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')",
            name="client_access_status",
        ),
        sa.CheckConstraint(
            "(status = 'REVOKED' AND revoked_at IS NOT NULL) OR "
            "(status <> 'REVOKED' AND revoked_at IS NULL)",
            name="revoked_status_matches_timestamp",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_client_access_grants_firm_client",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_client_access_grants_firm_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_client_access_grants"),
        sa.UniqueConstraint(
            "firm_id",
            "membership_id",
            "client_id",
            name="uq_client_access_grants_firm_membership_client",
        ),
    )
    op.create_index(
        "ix_client_access_grants_firm_id_client_id_status",
        "client_access_grants",
        ["firm_id", "client_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_client_access_grants_membership_id_status",
        "client_access_grants",
        ["membership_id", "status"],
        unique=False,
    )

    op.execute("ALTER TABLE client_access_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_access_grants FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY client_access_grants_tenant_isolation
        ON client_access_grants
        FOR ALL
        USING ({CLIENT_ACCESS_SCOPE})
        WITH CHECK ({CLIENT_ACCESS_SCOPE})
        """
    )

    op.execute("ALTER TABLE client_workspaces ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_workspaces FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY client_workspaces_tenant_isolation
        ON client_workspaces
        FOR ALL
        USING ({CLIENT_WORKSPACE_SCOPE})
        WITH CHECK ({CLIENT_WORKSPACE_SCOPE})
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS client_workspaces_tenant_isolation ON client_workspaces")
    op.execute("ALTER TABLE client_workspaces NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_workspaces DISABLE ROW LEVEL SECURITY")

    op.execute(
        "DROP POLICY IF EXISTS client_access_grants_tenant_isolation ON client_access_grants"
    )
    op.execute("ALTER TABLE client_access_grants NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE client_access_grants DISABLE ROW LEVEL SECURITY")

    op.drop_index(
        "ix_client_access_grants_membership_id_status",
        table_name="client_access_grants",
    )
    op.drop_index(
        "ix_client_access_grants_firm_id_client_id_status",
        table_name="client_access_grants",
    )
    op.drop_table("client_access_grants")

    op.drop_index("ix_firm_memberships_user_id_status", table_name="firm_memberships")
    op.drop_index(
        "ix_firm_memberships_firm_id_status_role",
        table_name="firm_memberships",
    )
    op.drop_table("firm_memberships")

    op.drop_index(
        "ix_client_workspaces_firm_id_status",
        table_name="client_workspaces",
    )
    op.drop_table("client_workspaces")
    op.drop_table("users")
    op.drop_table("firms")
