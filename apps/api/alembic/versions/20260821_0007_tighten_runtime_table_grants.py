"""Tighten runtime table grants to implemented Build 0 operations.

Revision ID: 20260821_0007
Revises: 20260821_0006
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "20260821_0007"
down_revision: str | None = "20260821_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROTECTED_TABLES = (
    "firms",
    "users",
    "firm_memberships",
    "client_workspaces",
    "client_access_grants",
)


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    runtime_role = _runtime_role()
    tables = ", ".join(PROTECTED_TABLES)
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    op.execute(f"GRANT SELECT, UPDATE ON firms, users TO {runtime_role}")
    op.execute(f"GRANT SELECT ON firm_memberships, client_access_grants TO {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON client_workspaces TO {runtime_role}")


def downgrade() -> None:
    runtime_role = _runtime_role()
    tables = ", ".join(PROTECTED_TABLES)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {runtime_role}")
