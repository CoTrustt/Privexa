"""Create the secure client file boundary.

Revision ID: 20260821_0008
Revises: 20260821_0007
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260821_0008"
down_revision: str | None = "20260821_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    op.create_table(
        "stored_files",
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column(
            "storage_provider",
            sa.Enum(
                "S3_COMPATIBLE",
                name="stored_file_storage_provider",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="S3_COMPATIBLE",
            nullable=False,
        ),
        sa.Column("storage_bucket", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("upload_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("object_etag", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING_UPLOAD",
                "AVAILABLE",
                "FAILED",
                "DELETED",
                name="stored_file_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="PENDING_UPLOAD",
            nullable=False,
        ),
        sa.Column(
            "sensitivity_level",
            sa.Enum(
                "STANDARD",
                "SENSITIVE",
                "RESTRICTED",
                name="stored_file_sensitivity_level",
                native_enum=False,
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("created_by_membership_id", UUID, nullable=False),
        sa.Column("upload_expires_at", TIMESTAMPTZ, nullable=False),
        sa.Column("completed_at", TIMESTAMPTZ, nullable=True),
        sa.Column("deleted_at", TIMESTAMPTZ, nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
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
            "status IN ('PENDING_UPLOAD', 'AVAILABLE', 'FAILED', 'DELETED')",
            name="stored_file_status",
        ),
        sa.CheckConstraint(
            "storage_provider IN ('S3_COMPATIBLE')",
            name="stored_file_storage_provider",
        ),
        sa.CheckConstraint(
            "sensitivity_level IN ('STANDARD', 'SENSITIVE', 'RESTRICTED')",
            name="stored_file_sensitivity_level",
        ),
        sa.CheckConstraint("size_bytes > 0", name="stored_file_size_positive"),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="stored_file_sha256_format",
        ),
        sa.CheckConstraint(
            "storage_key = 'objects/firms/' || firm_id::text || '/clients/' || "
            "client_id::text || '/files/' || id::text || '/original'",
            name="stored_file_canonical_storage_key",
        ),
        sa.CheckConstraint(
            "upload_storage_key = 'staging/firms/' || firm_id::text || '/clients/' || "
            "client_id::text || '/files/' || id::text || '/upload'",
            name="stored_file_canonical_upload_key",
        ),
        sa.CheckConstraint(
            "(status = 'DELETED' AND deleted_at IS NOT NULL) OR "
            "(status <> 'DELETED' AND deleted_at IS NULL)",
            name="stored_file_deleted_status_matches_timestamp",
        ),
        sa.CheckConstraint(
            "(status = 'FAILED' AND failure_code IS NOT NULL) OR "
            "(status <> 'FAILED' AND failure_code IS NULL)",
            name="stored_file_failed_status_matches_code",
        ),
        sa.CheckConstraint(
            "status <> 'AVAILABLE' OR completed_at IS NOT NULL",
            name="stored_file_available_has_completed_at",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_stored_files_firm_client",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "created_by_membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_stored_files_firm_creator_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stored_files"),
        sa.UniqueConstraint("firm_id", "client_id", "id", name="uq_stored_files_tenant_id"),
        sa.UniqueConstraint(
            "storage_bucket", "storage_key", name="uq_stored_files_object_location"
        ),
    )
    op.create_index(
        "ix_stored_files_firm_client_status_created",
        "stored_files",
        ["firm_id", "client_id", "status", "created_at"],
    )
    op.create_index(
        "ix_stored_files_firm_client_status_upload_expiry",
        "stored_files",
        ["firm_id", "client_id", "status", "upload_expires_at"],
    )

    op.execute("ALTER TABLE stored_files ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stored_files FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY stored_files_scoped_select
        ON stored_files FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY stored_files_scoped_insert
        ON stored_files FOR INSERT
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
            AND created_by_membership_id = privexa_private.current_context_uuid(
                'privexa.membership_id'
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY stored_files_scoped_update
        ON stored_files FOR UPDATE
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
        )
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
            AND created_by_membership_id IS NOT NULL
        )
        """
    )

    runtime_role = _runtime_role()
    op.execute(f"GRANT SELECT, INSERT ON stored_files TO {runtime_role}")
    op.execute(
        "GRANT UPDATE (status, object_etag, completed_at, deleted_at, failure_code, updated_at) "
        f"ON stored_files TO {runtime_role}"
    )


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON stored_files FROM {runtime_role}")
    for policy_name in (
        "stored_files_scoped_update",
        "stored_files_scoped_insert",
        "stored_files_scoped_select",
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON stored_files")
    op.execute("ALTER TABLE stored_files NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE stored_files DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_stored_files_firm_client_status_upload_expiry", table_name="stored_files")
    op.drop_index("ix_stored_files_firm_client_status_created", table_name="stored_files")
    op.drop_table("stored_files")
