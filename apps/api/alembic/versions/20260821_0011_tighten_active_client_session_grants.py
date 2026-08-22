"""Tighten active-client session table grants.

Revision ID: 20260821_0011
Revises: 20260821_0010
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "20260821_0011"
down_revision: str | None = "20260821_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON active_client_sessions FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT ON active_client_sessions TO {runtime_role}")
    op.execute(
        f"GRANT UPDATE (active_client_id, updated_at) ON active_client_sessions TO {runtime_role}"
    )


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON active_client_sessions FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON active_client_sessions TO {runtime_role}")
