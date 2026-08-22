from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Column, DateTime, String, Table, UniqueConstraint, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from privexa_api.db.base import TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.professional import (
    ActorProvenanceMixin,
    ArchivableMixin,
    ClientOwnedMixin,
    VersionedMixin,
    professional_object_constraints,
)


class KernelTestBase(DeclarativeBase):
    pass


# Metadata-only dependency stubs let SQLAlchemy compile the probe's composite foreign keys while
# the real Build 0 tables remain owned and migrated by the production Base metadata.
Table(
    "client_workspaces",
    KernelTestBase.metadata,
    Column("firm_id", Uuid, nullable=False),
    Column("id", Uuid, nullable=False),
    UniqueConstraint("firm_id", "id"),
)
Table(
    "firm_memberships",
    KernelTestBase.metadata,
    Column("firm_id", Uuid, nullable=False),
    Column("id", Uuid, nullable=False),
    UniqueConstraint("firm_id", "id"),
)


class ProfessionalRecordProbe(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    ClientOwnedMixin,
    ActorProvenanceMixin,
    VersionedMixin,
    ArchivableMixin,
    KernelTestBase,
):
    """Test-only representative model; no artificial production aggregate is introduced."""

    __tablename__ = "domain_kernel_records_test"
    __table_args__ = professional_object_constraints(__tablename__, archivable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)


class InvalidIdentityProfessionalProbe(
    TimestampMixin,
    ClientOwnedMixin,
    ActorProvenanceMixin,
    VersionedMixin,
    KernelTestBase,
):
    __tablename__ = "invalid_identity_professional_probe"
    __table_args__ = professional_object_constraints(__tablename__)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)


class InvalidTimestampProfessionalProbe(
    UUIDPrimaryKeyMixin,
    ClientOwnedMixin,
    ActorProvenanceMixin,
    VersionedMixin,
    KernelTestBase,
):
    __tablename__ = "invalid_timestamp_professional_probe"
    __table_args__ = professional_object_constraints(__tablename__)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


def record_probe(
    *,
    record_id: UUID,
    firm_id: UUID,
    client_id: UUID,
    membership_id: UUID,
    title: str = "Kernel probe",
) -> ProfessionalRecordProbe:
    return ProfessionalRecordProbe(
        id=record_id,
        firm_id=firm_id,
        client_id=client_id,
        created_by_membership_id=membership_id,
        updated_by_membership_id=membership_id,
        title=title,
    )
