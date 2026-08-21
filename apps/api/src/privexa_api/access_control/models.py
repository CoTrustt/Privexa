from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from privexa_api.access_control.enums import (
    ClientAccessStatus,
    FirmRole,
    MembershipStatus,
)
from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.types import constrained_enum

if TYPE_CHECKING:
    from privexa_api.clients.models import ClientWorkspace
    from privexa_api.identity.models import Firm, User


class FirmMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "firm_memberships"
    __table_args__ = (
        UniqueConstraint("firm_id", "user_id", name="uq_firm_memberships_firm_id_user_id"),
        UniqueConstraint("firm_id", "id", name="uq_firm_memberships_firm_id_id"),
        CheckConstraint(
            "role IN ('FIRM_OWNER', 'FIRM_ADMIN', 'CONSULTANT', 'REVIEWER', 'READ_ONLY')",
            name="firm_role",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')",
            name="membership_status",
        ),
        CheckConstraint(
            "(status = 'REVOKED' AND revoked_at IS NOT NULL) OR "
            "(status <> 'REVOKED' AND revoked_at IS NULL)",
            name="revoked_status_matches_timestamp",
        ),
        Index("ix_firm_memberships_user_id_status", "user_id", "status"),
        Index(
            "ix_firm_memberships_firm_id_status_role",
            "firm_id",
            "status",
            "role",
        ),
        Index(
            "uq_firm_memberships_stytch_member_id",
            "stytch_member_id",
            unique=True,
            postgresql_where=text("stytch_member_id IS NOT NULL"),
        ),
    )

    firm_id: Mapped[UUID] = mapped_column(
        ForeignKey("firms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    role: Mapped[FirmRole] = mapped_column(
        constrained_enum(FirmRole, name="firm_role"),
        nullable=False,
    )
    status: Mapped[MembershipStatus] = mapped_column(
        constrained_enum(MembershipStatus, name="membership_status"),
        nullable=False,
        default=MembershipStatus.ACTIVE,
        server_default=MembershipStatus.ACTIVE.value,
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stytch_member_id: Mapped[str | None] = mapped_column(String(255))

    firm: Mapped[Firm] = relationship(back_populates="memberships", lazy="raise")
    user: Mapped[User] = relationship(back_populates="memberships", lazy="raise")
    client_access_grants: Mapped[list[ClientAccessGrant]] = relationship(
        back_populates="membership",
        lazy="raise",
        viewonly=True,
    )


class ClientAccessGrant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "client_access_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id", "membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_client_access_grants_firm_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_client_access_grants_firm_client",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "firm_id",
            "membership_id",
            "client_id",
            name="uq_client_access_grants_firm_membership_client",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'REVOKED')",
            name="client_access_status",
        ),
        CheckConstraint(
            "(status = 'REVOKED' AND revoked_at IS NOT NULL) OR "
            "(status <> 'REVOKED' AND revoked_at IS NULL)",
            name="revoked_status_matches_timestamp",
        ),
        Index("ix_client_access_grants_membership_id_status", "membership_id", "status"),
        Index(
            "ix_client_access_grants_firm_id_client_id_status",
            "firm_id",
            "client_id",
            "status",
        ),
    )

    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[UUID] = mapped_column(nullable=False)
    membership_id: Mapped[UUID] = mapped_column(nullable=False)
    status: Mapped[ClientAccessStatus] = mapped_column(
        constrained_enum(ClientAccessStatus, name="client_access_status"),
        nullable=False,
        default=ClientAccessStatus.ACTIVE,
        server_default=ClientAccessStatus.ACTIVE.value,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    membership: Mapped[FirmMembership] = relationship(
        back_populates="client_access_grants",
        lazy="raise",
        viewonly=True,
    )
    client: Mapped[ClientWorkspace] = relationship(
        back_populates="access_grants",
        lazy="raise",
        viewonly=True,
    )
