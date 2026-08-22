from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from privexa_api.access_control.permissions import AuthorizationScope
from privexa_api.ai_provenance.enums import (
    AICostBasis,
    AIExecutionEventType,
    AIExecutionStage,
    AIProvenanceStatus,
    AIProviderAttemptKind,
    AIProviderAttemptStatus,
)
from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.types import constrained_enum
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel


class AIExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_executions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_ai_executions_firm_client",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_ai_executions_firm_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("firm_id", "id", name="uq_ai_executions_firm_id_id"),
        CheckConstraint(
            "status IN ('CREATED', 'EXECUTING', 'SUCCEEDED', 'REJECTED', 'FAILED', 'CANCELLED')",
            name="ai_execution_status",
        ),
        CheckConstraint(
            "sensitivity IN ('STANDARD', 'SENSITIVE', 'RESTRICTED')",
            name="ai_execution_sensitivity",
        ),
        CheckConstraint(
            "originating_channel IN ('WEB')",
            name="ai_execution_originating_channel",
        ),
        CheckConstraint(
            "authorization_scope IN ('FIRM', 'CLIENT', 'SELF')",
            name="ai_execution_authorization_scope",
        ),
        CheckConstraint(
            "(authorization_scope = 'CLIENT' AND client_id IS NOT NULL) OR "
            "(authorization_scope IN ('FIRM', 'SELF') AND client_id IS NULL)",
            name="ai_execution_authorization_scope_client",
        ),
        CheckConstraint(
            "error_stage IS NULL OR error_stage IN "
            "('VALIDATION', 'POLICY', 'PROTECTION', 'ROUTING', 'PROVIDER', "
            "'OUTPUT_VALIDATION', 'PROVENANCE', 'INTERNAL', 'CANCELLATION')",
            name="ai_execution_error_stage",
        ),
        CheckConstraint(
            "cost_basis IS NULL OR cost_basis IN ('PROVIDER_REPORTED', 'PRIVEXA_CALCULATED')",
            name="ai_execution_cost_basis",
        ),
        CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL)",
            name="ai_execution_cost_metadata_complete",
        ),
        CheckConstraint("source_reference_count >= 0", name="ai_execution_source_count"),
        CheckConstraint("provider_attempt_count >= 0", name="ai_execution_attempt_count"),
        CheckConstraint("retry_count >= 0", name="ai_execution_retry_count"),
        CheckConstraint("fallback_count >= 0", name="ai_execution_fallback_count"),
        CheckConstraint("last_event_sequence > 0", name="ai_execution_event_sequence"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at",
            name="ai_execution_period_valid",
        ),
        CheckConstraint(
            "output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'",
            name="ai_execution_output_hash_format",
        ),
        CheckConstraint(
            "prompt_template_hash IS NULL OR prompt_template_hash ~ '^[0-9a-f]{64}$'",
            name="ai_execution_prompt_hash_format",
        ),
        CheckConstraint(
            "trace_id IS NULL OR trace_id ~ '^[0-9a-f]{32}$'",
            name="ai_execution_trace_id_format",
        ),
        CheckConstraint(
            "span_id IS NULL OR span_id ~ '^[0-9a-f]{16}$'",
            name="ai_execution_span_id_format",
        ),
        CheckConstraint(
            "(status = 'SUCCEEDED' AND output_hash IS NOT NULL "
            "AND output_hash_algorithm IS NOT NULL AND output_canonicalization IS NOT NULL) "
            "OR (status <> 'SUCCEEDED' AND output_hash IS NULL "
            "AND output_hash_algorithm IS NULL AND output_canonicalization IS NULL)",
            name="ai_execution_output_hash_state",
        ),
        Index("ix_ai_executions_firm_client_started", "firm_id", "client_id", "started_at"),
        Index(
            "ix_ai_executions_firm_client_status_started",
            "firm_id",
            "client_id",
            "status",
            "started_at",
        ),
        Index(
            "ix_ai_executions_firm_task_version_started",
            "firm_id",
            "task_id",
            "task_version",
            "started_at",
        ),
        Index(
            "ix_ai_executions_firm_provider_model_started",
            "firm_id",
            "actual_provider",
            "actual_provider_model",
            "started_at",
        ),
        Index(
            "ix_ai_executions_trace_id",
            "trace_id",
            postgresql_where=text("trace_id IS NOT NULL"),
        ),
        Index(
            "ix_ai_executions_workflow_id",
            "workflow_id",
            postgresql_where=text("workflow_id IS NOT NULL"),
        ),
        Index(
            "ix_ai_executions_parent_execution_id",
            "parent_execution_id",
            postgresql_where=text("parent_execution_id IS NOT NULL"),
        ),
        Index(
            "ix_ai_executions_fallback_started",
            "firm_id",
            "started_at",
            postgresql_where=text("fallback_count > 0"),
        ),
    )

    parent_execution_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("ai_executions.id", ondelete="RESTRICT")
    )
    workflow_id: Mapped[UUID | None] = mapped_column()
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    firm_id: Mapped[UUID] = mapped_column(
        ForeignKey("firms.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[UUID | None] = mapped_column()
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    originating_channel: Mapped[OriginatingChannel] = mapped_column(
        constrained_enum(OriginatingChannel, name="ai_execution_originating_channel"),
        nullable=False,
    )
    authorization_scope: Mapped[AuthorizationScope] = mapped_column(
        constrained_enum(AuthorizationScope, name="ai_execution_authorization_scope"),
        nullable=False,
    )
    authorizing_permission: Mapped[str | None] = mapped_column(String(64))
    task_id: Mapped[str | None] = mapped_column(String(64))
    task_version: Mapped[str | None] = mapped_column(String(32))
    prompt_template_id: Mapped[str | None] = mapped_column(String(128))
    prompt_template_version: Mapped[str | None] = mapped_column(String(32))
    prompt_template_hash: Mapped[str | None] = mapped_column(String(64))
    sensitivity: Mapped[SensitivityLevel] = mapped_column(
        constrained_enum(SensitivityLevel, name="ai_execution_sensitivity"), nullable=False
    )
    status: Mapped[AIProvenanceStatus] = mapped_column(
        constrained_enum(AIProvenanceStatus, name="ai_execution_status"),
        nullable=False,
        default=AIProvenanceStatus.CREATED,
        server_default=AIProvenanceStatus.CREATED.value,
    )
    error_stage: Mapped[AIExecutionStage | None] = mapped_column(
        constrained_enum(AIExecutionStage, name="ai_execution_error_stage")
    )
    error_category: Mapped[str | None] = mapped_column(String(64))
    source_reference_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    policy_decision_id: Mapped[UUID | None] = mapped_column(unique=True)
    policy_allowed: Mapped[bool | None] = mapped_column(Boolean)
    policy_reason_code: Mapped[str | None] = mapped_column(String(64))
    policy_version: Mapped[str | None] = mapped_column(String(128))
    policy_hash: Mapped[str | None] = mapped_column(String(64))
    policy_decision_fingerprint: Mapped[str | None] = mapped_column(String(64))
    policy_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    policy_rule_references: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    allowed_provider_classes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    allowed_model_classes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    allowed_agent_authorities: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    zdr_requirement: Mapped[str | None] = mapped_column(String(32))
    redaction_requirement: Mapped[str | None] = mapped_column(String(32))
    protection_profile: Mapped[str | None] = mapped_column(String(64))
    max_input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    max_output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    max_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    timeout_ms: Mapped[int | None] = mapped_column(BigInteger)
    fallback_policy: Mapped[str | None] = mapped_column(String(64))

    pii_inspection_performed: Mapped[bool | None] = mapped_column(Boolean)
    pii_protection_applied: Mapped[bool | None] = mapped_column(Boolean)
    pii_protection_succeeded: Mapped[bool | None] = mapped_column(Boolean)
    pii_entity_count: Mapped[int | None] = mapped_column(Integer)
    pii_entity_summary: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    pii_protection_duration_ms: Mapped[int | None] = mapped_column(BigInteger)

    selected_model_alias: Mapped[str | None] = mapped_column(String(64))
    selected_provider: Mapped[str | None] = mapped_column(String(64))
    selected_provider_model: Mapped[str | None] = mapped_column(String(255))
    actual_provider: Mapped[str | None] = mapped_column(String(64))
    actual_provider_adapter: Mapped[str | None] = mapped_column(String(128))
    actual_provider_model: Mapped[str | None] = mapped_column(String(255))
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    provider_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    prompt_tokens: Mapped[int | None] = mapped_column(BigInteger)
    completion_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    cost_basis: Mapped[AICostBasis | None] = mapped_column(
        constrained_enum(AICostBasis, name="ai_execution_cost_basis")
    )
    cost_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(BigInteger)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    span_id: Mapped[str | None] = mapped_column(String(16))
    trace_sampled: Mapped[bool | None] = mapped_column(Boolean)
    output_hash: Mapped[str | None] = mapped_column(String(64))
    output_hash_algorithm: Mapped[str | None] = mapped_column(String(16))
    output_canonicalization: Mapped[str | None] = mapped_column(String(64))
    last_event_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AIExecutionEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_execution_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id", "execution_id"],
            ["ai_executions.firm_id", "ai_executions.id"],
            name="fk_ai_execution_events_firm_execution",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", "sequence_number", name="uq_ai_execution_events_sequence"),
        UniqueConstraint(
            "execution_id", "deduplication_key", name="uq_ai_execution_events_deduplication"
        ),
        CheckConstraint("sequence_number > 0", name="ai_execution_event_sequence_positive"),
        CheckConstraint(
            "jsonb_typeof(event_data) = 'object'", name="ai_execution_event_data_object"
        ),
        CheckConstraint(
            "event_type IN ('EXECUTION_CREATED', 'POLICY_EVALUATED', "
            "'PROTECTION_COMPLETED', 'ROUTE_SELECTED', 'PROVIDER_ATTEMPT_STARTED', "
            "'PROVIDER_ATTEMPT_SUCCEEDED', 'PROVIDER_ATTEMPT_FAILED', "
            "'EXECUTION_SUCCEEDED', 'EXECUTION_REJECTED', 'EXECUTION_FAILED', "
            "'EXECUTION_CANCELLED')",
            name="ai_execution_event_type",
        ),
        CheckConstraint(
            "stage IS NULL OR stage IN ('VALIDATION', 'POLICY', 'PROTECTION', "
            "'ROUTING', 'PROVIDER', 'OUTPUT_VALIDATION', 'PROVENANCE', 'INTERNAL', "
            "'CANCELLATION')",
            name="ai_execution_event_stage",
        ),
        CheckConstraint(
            "attempt_kind IS NULL OR attempt_kind IN ('PRIMARY', 'RETRY', 'FALLBACK')",
            name="ai_execution_attempt_kind",
        ),
        CheckConstraint(
            "attempt_status IS NULL OR attempt_status IN ('SUCCEEDED', 'FAILED')",
            name="ai_execution_attempt_status",
        ),
        CheckConstraint(
            "cost_basis IS NULL OR cost_basis IN ('PROVIDER_REPORTED', 'PRIVEXA_CALCULATED')",
            name="ai_execution_event_cost_basis",
        ),
        CheckConstraint(
            "(cost_amount IS NULL AND cost_currency IS NULL AND cost_basis IS NULL) OR "
            "(cost_amount IS NOT NULL AND cost_currency IS NOT NULL AND cost_basis IS NOT NULL)",
            name="ai_execution_event_cost_metadata_complete",
        ),
        CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="ai_execution_attempt_number_positive",
        ),
        CheckConstraint(
            "span_id IS NULL OR span_id ~ '^[0-9a-f]{16}$'",
            name="ai_execution_event_span_id_format",
        ),
        Index(
            "ix_ai_execution_events_firm_client_type_occurred",
            "firm_id",
            "client_id",
            "event_type",
            "occurred_at",
        ),
        Index(
            "ix_ai_execution_events_provider_request_id",
            "provider_request_id",
            postgresql_where=text("provider_request_id IS NOT NULL"),
        ),
    )

    execution_id: Mapped[UUID] = mapped_column(nullable=False)
    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[UUID | None] = mapped_column()
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[AIExecutionEventType] = mapped_column(
        constrained_enum(AIExecutionEventType, name="ai_execution_event_type"), nullable=False
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stage: Mapped[AIExecutionStage | None] = mapped_column(
        constrained_enum(AIExecutionStage, name="ai_execution_event_stage")
    )
    attempt_id: Mapped[UUID | None] = mapped_column()
    attempt_number: Mapped[int | None] = mapped_column(Integer)
    attempt_kind: Mapped[AIProviderAttemptKind | None] = mapped_column(
        constrained_enum(AIProviderAttemptKind, name="ai_execution_attempt_kind")
    )
    provider: Mapped[str | None] = mapped_column(String(64))
    provider_adapter: Mapped[str | None] = mapped_column(String(128))
    provider_model: Mapped[str | None] = mapped_column(String(255))
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    attempt_status: Mapped[AIProviderAttemptStatus | None] = mapped_column(
        constrained_enum(AIProviderAttemptStatus, name="ai_execution_attempt_status")
    )
    finish_reason: Mapped[str | None] = mapped_column(String(32))
    error_category: Mapped[str | None] = mapped_column(String(64))
    prompt_tokens: Mapped[int | None] = mapped_column(BigInteger)
    completion_tokens: Mapped[int | None] = mapped_column(BigInteger)
    total_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cached_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cost_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    cost_currency: Mapped[str | None] = mapped_column(String(3))
    cost_basis: Mapped[AICostBasis | None] = mapped_column(
        constrained_enum(AICostBasis, name="ai_execution_event_cost_basis")
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    span_id: Mapped[str | None] = mapped_column(String(16))
    event_data: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIExecutionSource(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_execution_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id", "execution_id"],
            ["ai_executions.firm_id", "ai_executions.id"],
            name="fk_ai_execution_sources_firm_execution",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("execution_id", "ordinal", name="uq_ai_execution_sources_ordinal"),
        UniqueConstraint(
            "execution_id", "source_type", "source_id", name="uq_ai_execution_sources_reference"
        ),
        CheckConstraint("ordinal > 0", name="ai_execution_source_ordinal_positive"),
        Index(
            "ix_ai_execution_sources_firm_client_reference",
            "firm_id",
            "client_id",
            "source_type",
            "source_id",
            "execution_id",
        ),
    )

    execution_id: Mapped[UUID] = mapped_column(nullable=False)
    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[UUID | None] = mapped_column()
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
