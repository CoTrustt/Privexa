from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIProviderRuntimeControl(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_provider_runtime_controls"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ai_provider_runtime_control_revision_positive"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ai_provider_runtime_control_hash_format",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= effective_at",
            name="ai_provider_runtime_control_period_valid",
        ),
        UniqueConstraint(
            "provider_id",
            "revision",
            name="uq_ai_provider_runtime_controls_provider_revision",
        ),
        Index(
            "uq_ai_provider_runtime_controls_current_provider",
            "provider_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIProviderCircuitState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_provider_circuit_states"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('PROVIDER', 'PROVIDER_MODEL')",
            name="ai_provider_circuit_state_scope_type",
        ),
        CheckConstraint(
            "state IN ('CLOSED', 'OPEN', 'HALF_OPEN')",
            name="ai_provider_circuit_state_state",
        ),
        CheckConstraint(
            "failure_count >= 0 AND half_open_successes >= 0",
            name="ai_provider_circuit_state_counts_nonnegative",
        ),
        CheckConstraint(
            "(scope_type = 'PROVIDER' AND provider_model = '') OR "
            "(scope_type = 'PROVIDER_MODEL' AND provider_model <> '')",
            name="ai_provider_circuit_state_model_scope",
        ),
        UniqueConstraint(
            "scope_type",
            "provider_id",
            "provider_model",
            name="uq_ai_provider_circuit_state_key",
        ),
    )

    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="CLOSED")
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    half_open_successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probe_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
