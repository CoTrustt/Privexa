"""Tighten AI availability tables to bounded runtime privileges.

Revision ID: 20260822_0018
Revises: 20260822_0017
Create Date: 2026-08-22
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "20260822_0018"
down_revision: str | None = "20260822_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    runtime_role = _runtime_role()
    tables = "ai_provider_runtime_controls, ai_provider_circuit_states"
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    op.execute(f"GRANT SELECT ON ai_provider_runtime_controls TO {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ai_provider_circuit_states TO {runtime_role}")


def downgrade() -> None:
    runtime_role = _runtime_role()
    tables = "ai_provider_runtime_controls, ai_provider_circuit_states"
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {tables} TO {runtime_role}")
