"""Add deterministic AI policy runtime controls and tenant overrides.

Revision ID: 20260821_0012
Revises: 20260821_0011
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260821_0012"
down_revision: str | None = "20260821_0011"
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
        "ai_policy_runtime_controls",
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "effective_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("superseded_at", TIMESTAMPTZ, nullable=True),
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
            "revision > 0",
            name="ai_policy_runtime_control_revision_positive",
        ),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ai_policy_runtime_control_hash_format",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= effective_at",
            name="ai_policy_runtime_control_period_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_policy_runtime_controls"),
        sa.UniqueConstraint(
            "task_id",
            "revision",
            name="uq_ai_policy_runtime_controls_task_revision",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ai_policy_runtime_controls_current_global "
        "ON ai_policy_runtime_controls ((1)) "
        "WHERE task_id IS NULL AND superseded_at IS NULL"
    )
    op.create_index(
        "uq_ai_policy_runtime_controls_current_task",
        "ai_policy_runtime_controls",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("task_id IS NOT NULL AND superseded_at IS NULL"),
    )

    op.create_table(
        "ai_policy_overrides",
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("sensitivity", sa.String(length=32), nullable=True),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("configuration_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "effective_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("superseded_at", TIMESTAMPTZ, nullable=True),
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
        sa.CheckConstraint("revision > 0", name="ai_policy_override_revision_positive"),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ai_policy_override_hash_format",
        ),
        sa.CheckConstraint(
            "sensitivity IS NULL OR sensitivity IN ('STANDARD', 'SENSITIVE', 'RESTRICTED')",
            name="ai_policy_override_sensitivity",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(constraints) = 'object'",
            name="ai_policy_override_constraints_object",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= effective_at",
            name="ai_policy_override_period_valid",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id"],
            ["firms.id"],
            name="fk_ai_policy_overrides_firm",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_ai_policy_overrides_firm_client",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_policy_overrides"),
        sa.UniqueConstraint(
            "firm_id",
            "client_id",
            "task_id",
            "sensitivity",
            "revision",
            name="uq_ai_policy_overrides_scope_revision",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_ai_policy_overrides_current_lookup",
        "ai_policy_overrides",
        ["firm_id", "client_id", "task_id", "sensitivity"],
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ai_policy_overrides_current_scope "
        "ON ai_policy_overrides (firm_id, client_id, task_id, sensitivity) "
        "NULLS NOT DISTINCT WHERE superseded_at IS NULL"
    )

    op.execute("ALTER TABLE ai_policy_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_policy_overrides FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY ai_policy_overrides_scoped_select
        ON ai_policy_overrides FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND (
                client_id IS NULL
                OR client_id = privexa_private.validated_client_id()
            )
        )
        """
    )

    runtime_role = _runtime_role()
    op.execute(f"GRANT SELECT ON ai_policy_runtime_controls TO {runtime_role}")
    op.execute(f"GRANT SELECT ON ai_policy_overrides TO {runtime_role}")
    op.get_bind().execute(
        sa.text(
            """
        INSERT INTO ai_policy_runtime_controls
            (task_id, enabled, revision, configuration_hash, id)
        VALUES
            (NULL, false, 1, :global_hash, :global_id),
            ('synthetic_text_summary', true, 1, :task_hash, :task_id)
        """
        ),
        {
            "global_hash": "fd5acff4086fd9dd45ea9bf14c08dbd63cffc385af6285c8a278b6c4738cd099",
            "task_hash": "82959bb0d28fe79ec9bb253c28bc6126a405320034d0585540fa42fb2cf034c3",
            "global_id": "00000000-0000-4000-8000-000000001101",
            "task_id": "00000000-0000-4000-8000-000000001102",
        },
    )


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON ai_policy_overrides FROM {runtime_role}")
    op.execute(f"REVOKE ALL PRIVILEGES ON ai_policy_runtime_controls FROM {runtime_role}")
    op.execute("DROP POLICY IF EXISTS ai_policy_overrides_scoped_select ON ai_policy_overrides")
    op.execute("ALTER TABLE ai_policy_overrides NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_policy_overrides DISABLE ROW LEVEL SECURITY")
    op.execute("DROP INDEX IF EXISTS uq_ai_policy_overrides_current_scope")
    op.drop_index("ix_ai_policy_overrides_current_lookup", table_name="ai_policy_overrides")
    op.drop_table("ai_policy_overrides")
    op.drop_index(
        "uq_ai_policy_runtime_controls_current_task",
        table_name="ai_policy_runtime_controls",
    )
    op.execute("DROP INDEX IF EXISTS uq_ai_policy_runtime_controls_current_global")
    op.drop_table("ai_policy_runtime_controls")
