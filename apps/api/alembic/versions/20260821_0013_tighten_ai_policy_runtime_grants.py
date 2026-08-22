"""Tighten AI policy tables to runtime read-only access.

Revision ID: 20260821_0013
Revises: 20260821_0012
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "20260821_0013"
down_revision: str | None = "20260821_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    runtime_role = _runtime_role()
    tables = "ai_policy_runtime_controls, ai_policy_overrides"
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    op.execute(f"GRANT SELECT ON {tables} TO {runtime_role}")


def downgrade() -> None:
    runtime_role = _runtime_role()
    tables = "ai_policy_runtime_controls, ai_policy_overrides"
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {runtime_role}")
