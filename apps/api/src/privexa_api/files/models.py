from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from privexa_api.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from privexa_api.db.types import constrained_enum
from privexa_api.files.enums import StorageProvider, StoredFileStatus
from privexa_api.security.enums import SensitivityLevel


class StoredFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Authoritative metadata for one client-owned object-storage file."""

    __tablename__ = "stored_files"
    __table_args__ = (
        ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_stored_files_firm_client",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "created_by_membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_stored_files_firm_creator_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("firm_id", "client_id", "id", name="uq_stored_files_tenant_id"),
        UniqueConstraint("storage_bucket", "storage_key", name="uq_stored_files_object_location"),
        CheckConstraint(
            "status IN ('PENDING_UPLOAD', 'AVAILABLE', 'FAILED', 'DELETED')",
            name="stored_file_status",
        ),
        CheckConstraint(
            "storage_provider IN ('S3_COMPATIBLE')",
            name="stored_file_storage_provider",
        ),
        CheckConstraint(
            "sensitivity_level IN ('STANDARD', 'SENSITIVE', 'RESTRICTED')",
            name="stored_file_sensitivity_level",
        ),
        CheckConstraint("size_bytes > 0", name="stored_file_size_positive"),
        CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="stored_file_sha256_format",
        ),
        CheckConstraint(
            "storage_key = 'objects/firms/' || firm_id::text || '/clients/' || "
            "client_id::text || '/files/' || id::text || '/original'",
            name="stored_file_canonical_storage_key",
        ),
        CheckConstraint(
            "upload_storage_key = 'staging/firms/' || firm_id::text || '/clients/' || "
            "client_id::text || '/files/' || id::text || '/upload'",
            name="stored_file_canonical_upload_key",
        ),
        CheckConstraint(
            "(status = 'DELETED' AND deleted_at IS NOT NULL) OR "
            "(status <> 'DELETED' AND deleted_at IS NULL)",
            name="stored_file_deleted_status_matches_timestamp",
        ),
        CheckConstraint(
            "(status = 'FAILED' AND failure_code IS NOT NULL) OR "
            "(status <> 'FAILED' AND failure_code IS NULL)",
            name="stored_file_failed_status_matches_code",
        ),
        CheckConstraint(
            "status <> 'AVAILABLE' OR completed_at IS NOT NULL",
            name="stored_file_available_has_completed_at",
        ),
        Index(
            "ix_stored_files_firm_client_status_created",
            "firm_id",
            "client_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_stored_files_firm_client_status_upload_expiry",
            "firm_id",
            "client_id",
            "status",
            "upload_expires_at",
        ),
    )

    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[UUID] = mapped_column(nullable=False)
    storage_provider: Mapped[StorageProvider] = mapped_column(
        constrained_enum(StorageProvider, name="stored_file_storage_provider"),
        nullable=False,
        default=StorageProvider.S3_COMPATIBLE,
        server_default=StorageProvider.S3_COMPATIBLE.value,
    )
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    upload_storage_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    object_etag: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[StoredFileStatus] = mapped_column(
        constrained_enum(StoredFileStatus, name="stored_file_status"),
        nullable=False,
        default=StoredFileStatus.PENDING_UPLOAD,
        server_default=StoredFileStatus.PENDING_UPLOAD.value,
    )
    sensitivity_level: Mapped[SensitivityLevel] = mapped_column(
        constrained_enum(SensitivityLevel, name="stored_file_sensitivity_level"),
        nullable=False,
    )
    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    upload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))
