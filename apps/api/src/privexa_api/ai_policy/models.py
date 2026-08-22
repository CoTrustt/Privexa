from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AIPolicyRuntimeControl(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_policy_runtime_controls"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ai_policy_runtime_control_revision_positive"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ai_policy_runtime_control_hash_format",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= effective_at",
            name="ai_policy_runtime_control_period_valid",
        ),
        UniqueConstraint(
            "task_id",
            "revision",
            name="uq_ai_policy_runtime_controls_task_revision",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "uq_ai_policy_runtime_controls_current_global",
            text("(task_id IS NULL)"),
            unique=True,
            postgresql_where=text("task_id IS NULL AND superseded_at IS NULL"),
        ),
        Index(
            "uq_ai_policy_runtime_controls_current_task",
            "task_id",
            unique=True,
            postgresql_where=text("task_id IS NOT NULL AND superseded_at IS NULL"),
        ),
    )

    task_id: Mapped[str | None] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIPolicyOverride(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ai_policy_overrides"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id"],
            ["firms.id"],
            name="fk_ai_policy_overrides_firm",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_ai_policy_overrides_firm_client",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision > 0", name="ai_policy_override_revision_positive"),
        CheckConstraint(
            "configuration_hash ~ '^[0-9a-f]{64}$'",
            name="ai_policy_override_hash_format",
        ),
        CheckConstraint(
            "sensitivity IS NULL OR sensitivity IN ('STANDARD', 'SENSITIVE', 'RESTRICTED')",
            name="ai_policy_override_sensitivity",
        ),
        CheckConstraint(
            "jsonb_typeof(constraints) = 'object'",
            name="ai_policy_override_constraints_object",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR superseded_at >= effective_at",
            name="ai_policy_override_period_valid",
        ),
        UniqueConstraint(
            "firm_id",
            "client_id",
            "task_id",
            "sensitivity",
            "revision",
            name="uq_ai_policy_overrides_scope_revision",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_ai_policy_overrides_current_lookup",
            "firm_id",
            "client_id",
            "task_id",
            "sensitivity",
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )

    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[UUID | None] = mapped_column()
    task_id: Mapped[str | None] = mapped_column(String(64))
    sensitivity: Mapped[str | None] = mapped_column(String(32))
    constraints: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
