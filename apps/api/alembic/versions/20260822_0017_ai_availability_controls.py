"""Add provider controls and cluster-shared AI circuit state.

Revision ID: 20260822_0017
Revises: 20260822_0016
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260822_0017"
down_revision: str | None = "20260822_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def upgrade() -> None:
    op.create_table(
        "ai_provider_runtime_controls",
        sa.Column("provider_id", sa.String(length=64), nullable=False),
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
        *_timestamps(),
        sa.CheckConstraint(
            "revision > 0",
            name="ai_provider_runtime_control_revision_positive",
        ),
        sa.CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ai_provider_runtime_control_hash_format",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= effective_at",
            name="ai_provider_runtime_control_period_valid",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_provider_runtime_controls"),
        sa.UniqueConstraint(
            "provider_id",
            "revision",
            name="uq_ai_provider_runtime_controls_provider_revision",
        ),
    )
    op.create_index(
        "uq_ai_provider_runtime_controls_current_provider",
        "ai_provider_runtime_controls",
        ["provider_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "ai_provider_circuit_states",
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("provider_id", sa.String(length=64), nullable=False),
        sa.Column("provider_model", sa.String(length=255), nullable=False),
        sa.Column("state", sa.String(length=16), server_default="CLOSED", nullable=False),
        sa.Column("failure_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_started_at", TIMESTAMPTZ, nullable=True),
        sa.Column("opened_at", TIMESTAMPTZ, nullable=True),
        sa.Column("half_open_successes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("probe_lease_until", TIMESTAMPTZ, nullable=True),
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        *_timestamps(),
        sa.CheckConstraint(
            "scope_type IN ('PROVIDER', 'PROVIDER_MODEL')",
            name="ai_provider_circuit_state_scope_type",
        ),
        sa.CheckConstraint(
            "state IN ('CLOSED', 'OPEN', 'HALF_OPEN')",
            name="ai_provider_circuit_state_state",
        ),
        sa.CheckConstraint(
            "failure_count >= 0 AND half_open_successes >= 0",
            name="ai_provider_circuit_state_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "(scope_type = 'PROVIDER' AND provider_model = '') OR "
            "(scope_type = 'PROVIDER_MODEL' AND provider_model <> '')",
            name="ai_provider_circuit_state_model_scope",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_provider_circuit_states"),
        sa.UniqueConstraint(
            "scope_type",
            "provider_id",
            "provider_model",
            name="uq_ai_provider_circuit_state_key",
        ),
    )

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO ai_provider_runtime_controls
                (provider_id, enabled, revision, configuration_hash, id)
            VALUES
                ('OPENROUTER', true, 1, :openrouter_hash, :openrouter_id),
                ('DETERMINISTIC', true, 1, :deterministic_hash, :deterministic_id)
            """
        ),
        {
            "openrouter_hash": ("c7ba71c5e76b2c6f8bdea489e39d2eb08246e99505d0c072316626ed4f887905"),
            "deterministic_hash": (
                "db714f051d3dfed1cc66e37d305f23d9621e6d44a5817be388f7f6272c672bc3"
            ),
            "openrouter_id": "00000000-0000-4000-8000-000000001701",
            "deterministic_id": "00000000-0000-4000-8000-000000001702",
        },
    )

    runtime_role = _runtime_role()
    op.execute(f"GRANT SELECT ON ai_provider_runtime_controls TO {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON ai_provider_circuit_states TO {runtime_role}")


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON ai_provider_circuit_states FROM {runtime_role}")
    op.execute(f"REVOKE ALL PRIVILEGES ON ai_provider_runtime_controls FROM {runtime_role}")
    op.drop_table("ai_provider_circuit_states")
    op.drop_index(
        "uq_ai_provider_runtime_controls_current_provider",
        table_name="ai_provider_runtime_controls",
    )
    op.drop_table("ai_provider_runtime_controls")
