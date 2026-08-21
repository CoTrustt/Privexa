from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.types import constrained_enum
from privexa_api.identity.enums import FirmStatus, UserStatus

if TYPE_CHECKING:
    from privexa_api.access_control.models import FirmMembership
    from privexa_api.clients.models import ClientWorkspace


class Firm(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "firms"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'ARCHIVED')",
            name="firm_status",
        ),
        CheckConstraint(
            "(status = 'ARCHIVED' AND archived_at IS NOT NULL) OR "
            "(status <> 'ARCHIVED' AND archived_at IS NULL)",
            name="archived_status_matches_timestamp",
        ),
        Index(
            "uq_firms_stytch_organization_id",
            "stytch_organization_id",
            unique=True,
            postgresql_where=text("stytch_organization_id IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[FirmStatus] = mapped_column(
        constrained_enum(FirmStatus, name="firm_status"),
        nullable=False,
        default=FirmStatus.ACTIVE,
        server_default=FirmStatus.ACTIVE.value,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stytch_organization_id: Mapped[str | None] = mapped_column(String(255))

    memberships: Mapped[list[FirmMembership]] = relationship(
        back_populates="firm",
        lazy="raise",
    )
    clients: Mapped[list[ClientWorkspace]] = relationship(
        back_populates="firm",
        lazy="raise",
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("email = lower(email)", name="email_is_normalized"),
        CheckConstraint("length(trim(email)) > 3", name="email_is_not_blank"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="user_status"),
    )

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        constrained_enum(UserStatus, name="user_status"),
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )

    memberships: Mapped[list[FirmMembership]] = relationship(
        back_populates="user",
        lazy="raise",
    )
