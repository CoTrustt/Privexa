from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from privexa_api.files.enums import StoredFileStatus
from privexa_api.security.enums import SensitivityLevel


class CreateFileUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    original_filename: str = Field(min_length=1, max_length=1024)
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int
    checksum_sha256: str = Field(min_length=64, max_length=64)
    sensitivity_level: SensitivityLevel | None = Field(default=None, strict=False)


class StoredFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)

    file_id: UUID
    original_filename: str
    mime_type: str
    size_bytes: int
    status: StoredFileStatus
    sensitivity_level: SensitivityLevel
    upload_expires_at: datetime
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SignedOperationResponse(BaseModel):
    url: str
    method: str
    required_headers: dict[str, str]
    expires_at: datetime


class CreateFileUploadResponse(BaseModel):
    file: StoredFileResponse
    upload: SignedOperationResponse


class DownloadFileResponse(BaseModel):
    url: str
    expires_at: datetime


def stored_file_response(stored_file) -> StoredFileResponse:
    return StoredFileResponse(
        file_id=stored_file.id,
        original_filename=stored_file.original_filename,
        mime_type=stored_file.mime_type,
        size_bytes=stored_file.size_bytes,
        status=stored_file.status,
        sensitivity_level=stored_file.sensitivity_level,
        upload_expires_at=stored_file.upload_expires_at,
        completed_at=stored_file.completed_at,
        created_at=stored_file.created_at,
        updated_at=stored_file.updated_at,
    )
