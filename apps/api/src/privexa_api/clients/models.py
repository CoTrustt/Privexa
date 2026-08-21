from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.types import constrained_enum

if TYPE_CHECKING:
    from privexa_api.access_control.models import ClientAccessGrant
    from privexa_api.identity.models import Firm


class ClientWorkspace(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The isolated workspace for one client organisation managed by one Firm."""

    __tablename__ = "client_workspaces"
    __table_args__ = (
        UniqueConstraint("firm_id", "id", name="uq_client_workspaces_firm_id_id"),
        CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'ARCHIVED')",
            name="client_workspace_status",
        ),
        CheckConstraint(
            "(status = 'ARCHIVED' AND archived_at IS NOT NULL) OR "
            "(status <> 'ARCHIVED' AND archived_at IS NULL)",
            name="archived_status_matches_timestamp",
        ),
        Index("ix_client_workspaces_firm_id_status", "firm_id", "status"),
    )

    firm_id: Mapped[UUID] = mapped_column(
        ForeignKey("firms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ClientWorkspaceStatus] = mapped_column(
        constrained_enum(ClientWorkspaceStatus, name="client_workspace_status"),
        nullable=False,
        default=ClientWorkspaceStatus.ACTIVE,
        server_default=ClientWorkspaceStatus.ACTIVE.value,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    firm: Mapped[Firm] = relationship(back_populates="clients", lazy="raise")
    access_grants: Mapped[list[ClientAccessGrant]] = relationship(
        back_populates="client",
        lazy="raise",
        viewonly=True,
    )
