"""Tighten runtime grants for the secure client file boundary.

Revision ID: 20260821_0009
Revises: 20260821_0008
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "20260821_0009"
down_revision: str | None = "20260821_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON stored_files FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT ON stored_files TO {runtime_role}")
    op.execute(
        "GRANT UPDATE (status, object_etag, completed_at, deleted_at, failure_code, updated_at) "
        f"ON stored_files TO {runtime_role}"
    )


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON stored_files FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON stored_files TO {runtime_role}")
