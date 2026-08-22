from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from privexa_api.access_control.models import FirmMembership
    from privexa_api.clients.models import ClientWorkspace


class ActiveClientSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Server-owned active client for one validated provider member session."""

    __tablename__ = "active_client_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id", "membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_active_client_sessions_firm_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "active_client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_active_client_sessions_firm_client",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "firm_id",
            "membership_id",
            "session_fingerprint",
            name="uq_active_client_sessions_firm_membership_session",
        ),
        CheckConstraint(
            "session_fingerprint ~ '^[0-9a-f]{64}$'",
            name="session_fingerprint_sha256",
        ),
        Index(
            "ix_active_client_sessions_firm_membership_active_client",
            "firm_id",
            "membership_id",
            "active_client_id",
        ),
    )

    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    active_client_id: Mapped[UUID] = mapped_column(nullable=False)
    session_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    membership: Mapped[FirmMembership] = relationship(lazy="raise", viewonly=True)
    active_client: Mapped[ClientWorkspace] = relationship(lazy="raise", viewonly=True)
