"""Add privacy-safe AI execution provenance.

Revision ID: 20260822_0014
Revises: 20260821_0013
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260822_0014"
down_revision: str | None = "20260821_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _enum(*values: str, name: str, length: int) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        native_enum=False,
        create_constraint=False,
    )


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def _scope_expression() -> str:
    return """
        firm_id = privexa_private.validated_firm_id()
        AND client_id IS NOT DISTINCT FROM
            privexa_private.current_context_uuid('privexa.client_id')
        AND (
            client_id IS NULL
            OR client_id = privexa_private.validated_client_id()
        )
    """


def upgrade() -> None:
    op.create_table(
        "ai_executions",
        sa.Column("parent_execution_id", UUID, nullable=True),
        sa.Column("workflow_id", UUID, nullable=True),
        sa.Column("request_id", UUID, nullable=False),
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=True),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column(
            "originating_channel",
            _enum("WEB", name="ai_execution_originating_channel", length=32),
            nullable=False,
        ),
        sa.Column(
            "authorization_scope",
            _enum("FIRM", "CLIENT", "SELF", name="ai_execution_authorization_scope", length=32),
            nullable=False,
        ),
        sa.Column("authorizing_permission", sa.String(length=64), nullable=True),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("task_version", sa.String(length=32), nullable=True),
        sa.Column("prompt_template_id", sa.String(length=128), nullable=True),
        sa.Column("prompt_template_version", sa.String(length=32), nullable=True),
        sa.Column("prompt_template_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "sensitivity",
            _enum(
                "STANDARD",
                "SENSITIVE",
                "RESTRICTED",
                name="ai_execution_sensitivity",
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum(
                "CREATED",
                "EXECUTING",
                "SUCCEEDED",
                "REJECTED",
                "FAILED",
                "CANCELLED",
                name="ai_execution_status",
                length=32,
            ),
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column(
            "error_stage",
            _enum(
                "VALIDATION",
                "POLICY",
                "PROTECTION",
                "ROUTING",
                "PROVIDER",
                "OUTPUT_VALIDATION",
                "PROVENANCE",
                "INTERNAL",
                "CANCELLATION",
                name="ai_execution_error_stage",
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("source_reference_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("policy_decision_id", UUID, nullable=True),
        sa.Column("policy_allowed", sa.Boolean(), nullable=True),
        sa.Column("policy_reason_code", sa.String(length=64), nullable=True),
        sa.Column("policy_version", sa.String(length=128), nullable=True),
        sa.Column("policy_hash", sa.String(length=64), nullable=True),
        sa.Column("policy_decision_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("policy_evaluated_at", TIMESTAMPTZ, nullable=True),
        sa.Column(
            "policy_rule_references", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "allowed_provider_classes", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "allowed_model_classes", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "allowed_agent_authorities",
            JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("zdr_requirement", sa.String(length=32), nullable=True),
        sa.Column("redaction_requirement", sa.String(length=32), nullable=True),
        sa.Column("protection_profile", sa.String(length=64), nullable=True),
        sa.Column("max_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("max_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("max_cost_usd", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("timeout_ms", sa.BigInteger(), nullable=True),
        sa.Column("fallback_policy", sa.String(length=64), nullable=True),
        sa.Column("pii_inspection_performed", sa.Boolean(), nullable=True),
        sa.Column("pii_protection_applied", sa.Boolean(), nullable=True),
        sa.Column("pii_protection_succeeded", sa.Boolean(), nullable=True),
        sa.Column("pii_entity_count", sa.Integer(), nullable=True),
        sa.Column(
            "pii_entity_summary", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("pii_protection_duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("selected_model_alias", sa.String(length=64), nullable=True),
        sa.Column("selected_provider", sa.String(length=64), nullable=True),
        sa.Column("selected_provider_model", sa.String(length=255), nullable=True),
        sa.Column("actual_provider", sa.String(length=64), nullable=True),
        sa.Column("actual_provider_adapter", sa.String(length=128), nullable=True),
        sa.Column("actual_provider_model", sa.String(length=255), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("provider_attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fallback_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=True),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "cost_basis",
            _enum(
                "PROVIDER_REPORTED",
                "PRIVEXA_CALCULATED",
                name="ai_execution_cost_basis",
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("cost_complete", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "started_at", TIMESTAMPTZ, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("completed_at", TIMESTAMPTZ, nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=True),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.Column("trace_sampled", sa.Boolean(), nullable=True),
        sa.Column("output_hash", sa.String(length=64), nullable=True),
        sa.Column("output_hash_algorithm", sa.String(length=16), nullable=True),
        sa.Column("output_canonicalization", sa.String(length=64), nullable=True),
        sa.Column("last_event_sequence", sa.Integer(), server_default="1", nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at", TIMESTAMPTZ, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", TIMESTAMPTZ, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'EXECUTING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'CANCELLED')",
            name="ai_execution_status",
        ),
        sa.CheckConstraint(
            "sensitivity IN ('STANDARD', 'SENSITIVE', 'RESTRICTED')",
            name="ai_execution_sensitivity",
        ),
        sa.CheckConstraint(
            "originating_channel IN ('WEB')", name="ai_execution_originating_channel"
        ),
        sa.CheckConstraint(
            "authorization_scope IN ('FIRM', 'CLIENT', 'SELF')",
            name="ai_execution_authorization_scope",
        ),
        sa.CheckConstraint(
            "error_stage IS NULL OR error_stage IN "
            "('VALIDATION', 'POLICY', 'PROTECTION', 'ROUTING', 'PROVIDER', "
            "'OUTPUT_VALIDATION', 'PROVENANCE', 'INTERNAL', 'CANCELLATION')",
            name="ai_execution_error_stage",
        ),
        sa.CheckConstraint(
            "cost_basis IS NULL OR cost_basis IN ('PROVIDER_REPORTED', 'PRIVEXA_CALCULATED')",
            name="ai_execution_cost_basis",
        ),
        sa.CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL)",
            name="ai_execution_cost_metadata_complete",
        ),
        sa.CheckConstraint("source_reference_count >= 0", name="ai_execution_source_count"),
        sa.CheckConstraint("provider_attempt_count >= 0", name="ai_execution_attempt_count"),
        sa.CheckConstraint("retry_count >= 0", name="ai_execution_retry_count"),
        sa.CheckConstraint("fallback_count >= 0", name="ai_execution_fallback_count"),
        sa.CheckConstraint("last_event_sequence > 0", name="ai_execution_event_sequence"),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="ai_execution_period_valid"
        ),
        sa.CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="ai_execution_output_hash_format",
        ),
        sa.CheckConstraint(
            "prompt_template_hash IS NULL OR prompt_template_hash ~ '^[0-9a-f]{64}$'",
            name="ai_execution_prompt_hash_format",
        ),
        sa.CheckConstraint(
            "trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'", name="ai_execution_trace_id_format"
        ),
        sa.CheckConstraint(
            "span_id IS NULL OR span_id ~ '^[0-9a-f]{16}$'", name="ai_execution_span_id_format"
        ),
        sa.CheckConstraint(
            "(status = 'SUCCEEDED' AND output_hash IS NOT NULL "
            "AND output_hash_algorithm IS NOT NULL AND output_canonicalization IS NOT NULL) "
            "OR (status <> 'SUCCEEDED' AND output_hash IS NULL "
            "AND output_hash_algorithm IS NULL AND output_canonicalization IS NULL)",
            name="ai_execution_output_hash_state",
        ),
        sa.ForeignKeyConstraint(
            ["parent_execution_id"],
            ["ai_executions.id"],
            name="fk_ai_executions_parent",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id"], ["firms.id"], name="fk_ai_executions_firm", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ai_executions_user", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_ai_executions_firm_client",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_ai_executions_firm_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_executions"),
        sa.UniqueConstraint("firm_id", "id", name="uq_ai_executions_firm_id_id"),
        sa.UniqueConstraint("policy_decision_id", name="uq_ai_executions_policy_decision_id"),
    )
    op.create_index(
        "ix_ai_executions_firm_client_started",
        "ai_executions",
        ["firm_id", "client_id", "started_at"],
    )
    op.create_index(
        "ix_ai_executions_firm_client_status_started",
        "ai_executions",
        ["firm_id", "client_id", "status", "started_at"],
    )
    op.create_index(
        "ix_ai_executions_firm_task_version_started",
        "ai_executions",
        ["firm_id", "task_id", "task_version", "started_at"],
    )
    op.create_index(
        "ix_ai_executions_firm_provider_model_started",
        "ai_executions",
        ["firm_id", "actual_provider", "actual_provider_model", "started_at"],
    )
    op.create_index(
        "ix_ai_executions_trace_id",
        "ai_executions",
        ["trace_id"],
        postgresql_where=sa.text("trace_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_executions_workflow_id",
        "ai_executions",
        ["workflow_id"],
        postgresql_where=sa.text("workflow_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_executions_parent_execution_id",
        "ai_executions",
        ["parent_execution_id"],
        postgresql_where=sa.text("parent_execution_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_executions_fallback_started",
        "ai_executions",
        ["firm_id", "started_at"],
        postgresql_where=sa.text("fallback_count > 0"),
    )

    op.create_table(
        "ai_execution_events",
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("deduplication_key", sa.String(length=128), nullable=False),
        sa.Column(
            "event_type",
            _enum(
                "EXECUTION_CREATED",
                "POLICY_EVALUATED",
                "PROTECTION_COMPLETED",
                "ROUTE_SELECTED",
                "PROVIDER_ATTEMPT_STARTED",
                "PROVIDER_ATTEMPT_SUCCEEDED",
                "PROVIDER_ATTEMPT_FAILED",
                "EXECUTION_SUCCEEDED",
                "EXECUTION_REJECTED",
                "EXECUTION_FAILED",
                "EXECUTION_CANCELLED",
                name="ai_execution_event_type",
                length=64,
            ),
            nullable=False,
        ),
        sa.Column(
            "occurred_at", TIMESTAMPTZ, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "stage",
            _enum(
                "VALIDATION",
                "POLICY",
                "PROTECTION",
                "ROUTING",
                "PROVIDER",
                "OUTPUT_VALIDATION",
                "PROVENANCE",
                "INTERNAL",
                "CANCELLATION",
                name="ai_execution_event_stage",
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("attempt_id", UUID, nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=True),
        sa.Column(
            "attempt_kind",
            _enum(
                "PRIMARY",
                "RETRY",
                "FALLBACK",
                name="ai_execution_attempt_kind",
                length=16,
            ),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("provider_adapter", sa.String(length=128), nullable=True),
        sa.Column("provider_model", sa.String(length=255), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column(
            "attempt_status",
            _enum(
                "SUCCEEDED",
                "FAILED",
                name="ai_execution_attempt_status",
                length=16,
            ),
            nullable=True,
        ),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("error_category", sa.String(length=64), nullable=True),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=True),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=True),
        sa.Column("total_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cached_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cost_amount", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("cost_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "cost_basis",
            _enum(
                "PROVIDER_REPORTED",
                "PRIVEXA_CALCULATED",
                name="ai_execution_event_cost_basis",
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("span_id", sa.String(length=16), nullable=True),
        sa.Column("event_data", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at", TIMESTAMPTZ, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint("sequence_number > 0", name="ai_execution_event_sequence_positive"),
        sa.CheckConstraint(
            "jsonb_typeof(event_data) = 'object'", name="ai_execution_event_data_object"
        ),
        sa.CheckConstraint(
            "event_type IN ('EXECUTION_CREATED', 'POLICY_EVALUATED', 'PROTECTION_COMPLETED', "
            "'ROUTE_SELECTED', 'PROVIDER_ATTEMPT_STARTED', 'PROVIDER_ATTEMPT_SUCCEEDED', "
            "'PROVIDER_ATTEMPT_FAILED', 'EXECUTION_SUCCEEDED', 'EXECUTION_REJECTED', "
            "'EXECUTION_FAILED', 'EXECUTION_CANCELLED')",
            name="ai_execution_event_type",
        ),
        sa.CheckConstraint(
            "attempt_kind IS NULL OR attempt_kind IN ('PRIMARY', 'RETRY', 'FALLBACK')",
            name="ai_execution_attempt_kind",
        ),
        sa.CheckConstraint(
            "attempt_status IS NULL OR attempt_status IN ('SUCCEEDED', 'FAILED')",
            name="ai_execution_attempt_status",
        ),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('VALIDATION', 'POLICY', 'PROTECTION', "
            "'ROUTING', 'PROVIDER', 'OUTPUT_VALIDATION', 'PROVENANCE', 'INTERNAL', "
            "'CANCELLATION')",
            name="ai_execution_event_stage",
        ),
        sa.CheckConstraint(
            "cost_basis IS NULL OR cost_basis IN ('PROVIDER_REPORTED', 'PRIVEXA_CALCULATED')",
            name="ai_execution_event_cost_basis",
        ),
        sa.CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL)",
            name="ai_execution_event_cost_metadata_complete",
        ),
        sa.CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="ai_execution_attempt_number_positive",
        ),
        sa.CheckConstraint(
            "span_id IS NULL OR span_id ~ '^[0-9a-f]{16}$'",
            name="ai_execution_event_span_id_format",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "execution_id"],
            ["ai_executions.firm_id", "ai_executions.id"],
            name="fk_ai_execution_events_firm_execution",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_execution_events"),
        sa.UniqueConstraint(
            "execution_id", "sequence_number", name="uq_ai_execution_events_sequence"
        ),
        sa.UniqueConstraint(
            "execution_id", "deduplication_key", name="uq_ai_execution_events_deduplication"
        ),
    )
    op.create_index(
        "ix_ai_execution_events_firm_client_type_occurred",
        "ai_execution_events",
        ["firm_id", "client_id", "event_type", "occurred_at"],
    )
    op.create_index(
        "ix_ai_execution_events_provider_request_id",
        "ai_execution_events",
        ["provider_request_id"],
        postgresql_where=sa.text("provider_request_id IS NOT NULL"),
    )

    op.create_table(
        "ai_execution_sources",
        sa.Column("execution_id", UUID, nullable=False),
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at", TIMESTAMPTZ, server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.CheckConstraint("ordinal > 0", name="ai_execution_source_ordinal_positive"),
        sa.ForeignKeyConstraint(
            ["firm_id", "execution_id"],
            ["ai_executions.firm_id", "ai_executions.id"],
            name="fk_ai_execution_sources_firm_execution",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_execution_sources"),
        sa.UniqueConstraint("execution_id", "ordinal", name="uq_ai_execution_sources_ordinal"),
        sa.UniqueConstraint(
            "execution_id", "source_type", "source_id", name="uq_ai_execution_sources_reference"
        ),
    )
    op.create_index(
        "ix_ai_execution_sources_firm_client_reference",
        "ai_execution_sources",
        ["firm_id", "client_id", "source_type", "source_id", "execution_id"],
    )

    scope = _scope_expression()
    for table in ("ai_executions", "ai_execution_events", "ai_execution_sources"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scoped_select ON {table} FOR SELECT USING ({scope})")
        insert_scope = scope
        if table != "ai_executions":
            insert_scope += f"""
                AND EXISTS (
                    SELECT 1
                    FROM ai_executions AS parent_execution
                    WHERE parent_execution.id = {table}.execution_id
                      AND parent_execution.firm_id = {table}.firm_id
                      AND parent_execution.client_id IS NOT DISTINCT FROM {table}.client_id
                )
            """
        op.execute(
            f"CREATE POLICY {table}_scoped_insert ON {table} FOR INSERT WITH CHECK ({insert_scope})"
        )
    op.execute("DROP POLICY ai_executions_scoped_insert ON ai_executions")
    op.execute(
        "CREATE POLICY ai_executions_scoped_insert ON ai_executions FOR INSERT WITH CHECK ("
        f"{scope} AND user_id = privexa_private.current_context_uuid('privexa.user_id') "
        "AND membership_id = "
        "privexa_private.current_context_uuid('privexa.membership_id'))"
    )
    op.execute(
        f"CREATE POLICY ai_executions_scoped_update ON ai_executions FOR UPDATE "
        f"USING ({scope}) WITH CHECK ({scope})"
    )

    runtime_role = _runtime_role()
    tables = "ai_executions, ai_execution_events, ai_execution_sources"
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT ON {tables} TO {runtime_role}")
    mutable_columns = (
        "status, error_stage, error_category, policy_decision_id, policy_allowed, "
        "policy_reason_code, policy_version, policy_hash, policy_decision_fingerprint, "
        "policy_evaluated_at, policy_rule_references, allowed_provider_classes, "
        "allowed_model_classes, allowed_agent_authorities, zdr_requirement, "
        "redaction_requirement, protection_profile, max_input_tokens, max_output_tokens, "
        "max_cost_usd, timeout_ms, fallback_policy, pii_inspection_performed, "
        "pii_protection_applied, pii_protection_succeeded, pii_entity_count, "
        "pii_entity_summary, pii_protection_duration_ms, selected_model_alias, "
        "selected_provider, selected_provider_model, actual_provider, actual_provider_adapter, "
        "actual_provider_model, finish_reason, provider_attempt_count, retry_count, "
        "fallback_count, prompt_tokens, completion_tokens, total_tokens, cached_tokens, "
        "reasoning_tokens, cost_amount, cost_currency, cost_basis, cost_complete, "
        "completed_at, latency_ms, output_hash, output_hash_algorithm, "
        "output_canonicalization, last_event_sequence, updated_at"
    )
    op.execute(f"GRANT UPDATE ({mutable_columns}) ON ai_executions TO {runtime_role}")


def downgrade() -> None:
    runtime_role = _runtime_role()
    tables = "ai_execution_sources, ai_execution_events, ai_executions"
    op.execute(f"REVOKE ALL PRIVILEGES ON {tables} FROM {runtime_role}")
    for table in ("ai_execution_sources", "ai_execution_events", "ai_executions"):
        op.execute(f"DROP POLICY IF EXISTS {table}_scoped_insert ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_scoped_select ON {table}")
    op.execute("DROP POLICY IF EXISTS ai_executions_scoped_update ON ai_executions")
    op.drop_table("ai_execution_sources")
    op.drop_table("ai_execution_events")
    op.drop_table("ai_executions")
