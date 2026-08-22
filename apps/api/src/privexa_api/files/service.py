from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.files.enums import StorageProvider, StoredFileStatus
from privexa_api.files.errors import (
    FileNotFoundError,
    FileStateConflictError,
    FileStorageUnavailableError,
    FileValidationError,
)
from privexa_api.files.models import StoredFile
from privexa_api.files.policy import (
    ValidatedFileMetadata,
    build_content_disposition,
    validate_file_metadata,
)
from privexa_api.files.repository import StoredFileRepository
from privexa_api.files.schemas import CreateFileUploadRequest
from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.errors import SensitivityPolicyViolation
from privexa_api.security.execution_context import (
    ExecutionContext,
    require_trusted_execution_context,
)
from privexa_api.security.sensitivity import SensitivityPolicy
from privexa_api.storage.gateway import (
    ObjectHead,
    ObjectLocation,
    ObjectStorageGateway,
    ObjectStorageOperationError,
    SignedStorageOperation,
)
from privexa_api.storage.keys import build_stored_file_keys

LOGGER = logging.getLogger("privexa.files")
_FILE_HANDLER_NAME = "privexa-files-json"


def configure_file_logging() -> None:
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _FILE_HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_FILE_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


@dataclass(frozen=True, slots=True)
class UploadInitiation:
    stored_file: StoredFile
    upload: SignedStorageOperation


@dataclass(frozen=True, slots=True)
class CompletionOutcome:
    stored_file: StoredFile | None
    problem_code: str | None = None
    problem_detail: str | None = None


class StoredFileService:
    def __init__(
        self,
        *,
        storage: ObjectStorageGateway,
        bucket: str,
        upload_ttl_seconds: int,
        upload_completion_grace_seconds: int,
        download_ttl_seconds: int,
        max_upload_size_bytes: int,
    ) -> None:
        self._storage = storage
        self._bucket = bucket
        self._upload_ttl_seconds = upload_ttl_seconds
        self._upload_completion_grace_seconds = upload_completion_grace_seconds
        self._download_ttl_seconds = download_ttl_seconds
        self._max_upload_size_bytes = max_upload_size_bytes

    @staticmethod
    def _context(
        session: Session,
        context: ExecutionContext,
        permission: Permission,
    ) -> ExecutionContext:
        trusted = require_trusted_execution_context(context)
        trusted.require_capability(permission)
        require_matching_execution_context_scope(session, trusted)
        return trusted

    @staticmethod
    def _log(event: str, *, context: ExecutionContext, file_id: UUID, **fields: object) -> None:
        LOGGER.info(
            json.dumps(
                {
                    "event": event,
                    **context.safe_logging_fields(),
                    "file_id": str(file_id),
                    **fields,
                },
                sort_keys=True,
                default=str,
            )
        )

    def _locations(self, stored_file: StoredFile) -> tuple[ObjectLocation, ObjectLocation]:
        expected = build_stored_file_keys(
            firm_id=stored_file.firm_id,
            client_id=stored_file.client_id,
            file_id=stored_file.id,
        )
        if (
            stored_file.storage_bucket != self._bucket
            or stored_file.upload_storage_key != expected.upload_key
            or stored_file.storage_key != expected.storage_key
        ):
            raise FileStorageUnavailableError
        return (
            ObjectLocation(bucket=self._bucket, key=expected.upload_key),
            ObjectLocation(bucket=self._bucket, key=expected.storage_key),
        )

    def _raise_resource_unavailable(
        self,
        *,
        context: ExecutionContext,
        file_id: UUID,
        operation: str,
    ) -> NoReturn:
        self._log(
            "file.resource_unavailable",
            context=context,
            file_id=file_id,
            operation=operation,
            decision="DENY",
            reason_code="RESOURCE_NOT_FOUND",
        )
        raise FileNotFoundError

    @staticmethod
    def _head_matches(head: ObjectHead, metadata: ValidatedFileMetadata | StoredFile) -> bool:
        return (
            head.size_bytes == metadata.size_bytes
            and head.content_type == metadata.mime_type
            and head.checksum_sha256 == metadata.checksum_sha256
        )

    def initiate_upload(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        request: CreateFileUploadRequest,
    ) -> UploadInitiation:
        trusted = self._context(session, context, Permission.FILE_CREATE)
        validated = validate_file_metadata(
            original_filename=request.original_filename,
            mime_type=request.mime_type,
            size_bytes=request.size_bytes,
            checksum_sha256=request.checksum_sha256,
            max_size_bytes=self._max_upload_size_bytes,
        )
        try:
            sensitivity = SensitivityPolicy.classify_new(
                declared=request.sensitivity_level,
                inherited=(SensitivityLevel.SENSITIVE,),
            )
        except SensitivityPolicyViolation as error:
            raise FileValidationError(
                code="INVALID_FILE_SENSITIVITY",
                detail="Client files must be classified as SENSITIVE or RESTRICTED.",
            ) from error

        file_id = uuid4()
        keys = build_stored_file_keys(
            firm_id=trusted.firm_id,
            client_id=trusted.client_id,  # type: ignore[arg-type]
            file_id=file_id,
        )
        expires_at = datetime.now(UTC) + timedelta(seconds=self._upload_ttl_seconds)
        stored_file = StoredFile(
            id=file_id,
            firm_id=trusted.firm_id,
            client_id=trusted.client_id,
            storage_provider=StorageProvider.S3_COMPATIBLE,
            storage_bucket=self._bucket,
            storage_key=keys.storage_key,
            upload_storage_key=keys.upload_key,
            original_filename=validated.original_filename,
            mime_type=validated.mime_type,
            size_bytes=validated.size_bytes,
            checksum_sha256=validated.checksum_sha256,
            status=StoredFileStatus.PENDING_UPLOAD,
            sensitivity_level=sensitivity,
            created_by_membership_id=trusted.membership_id,
            upload_expires_at=expires_at,
        )
        StoredFileRepository.add(session, stored_file=stored_file)
        try:
            upload = self._storage.create_upload_url(
                location=ObjectLocation(bucket=self._bucket, key=keys.upload_key),
                content_type=validated.mime_type,
                size_bytes=validated.size_bytes,
                checksum_sha256=validated.checksum_sha256,
                expires_at=expires_at,
                ttl_seconds=self._upload_ttl_seconds,
            )
        except ObjectStorageOperationError as error:
            raise FileStorageUnavailableError from error
        self._log(
            "file.upload_requested",
            context=trusted,
            file_id=file_id,
            status=stored_file.status.value,
            sensitivity=sensitivity.value,
        )
        return UploadInitiation(stored_file=stored_file, upload=upload)

    def get_metadata(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        file_id: UUID,
    ) -> StoredFile:
        trusted = self._context(session, context, Permission.FILE_READ)
        stored_file = StoredFileRepository.get(
            session,
            context=trusted.to_client_context(),
            file_id=file_id,
        )
        if stored_file is None or stored_file.status == StoredFileStatus.DELETED:
            self._raise_resource_unavailable(
                context=trusted,
                file_id=file_id,
                operation="read_metadata",
            )
        trusted.with_minimum_sensitivity(stored_file.sensitivity_level)
        return stored_file

    def complete_upload(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        file_id: UUID,
    ) -> CompletionOutcome:
        trusted = self._context(session, context, Permission.FILE_CREATE)
        stored_file = StoredFileRepository.get(
            session,
            context=trusted.to_client_context(),
            file_id=file_id,
            for_update=True,
        )
        if stored_file is None:
            self._raise_resource_unavailable(
                context=trusted,
                file_id=file_id,
                operation="complete_upload",
            )
        if stored_file.status == StoredFileStatus.AVAILABLE:
            return CompletionOutcome(stored_file=stored_file)
        if stored_file.status in {StoredFileStatus.FAILED, StoredFileStatus.DELETED}:
            raise FileStateConflictError(
                code="FILE_STATE_CONFLICT",
                detail="This file upload cannot be completed in its current state.",
            )

        upload_location, storage_location = self._locations(stored_file)
        deadline = stored_file.upload_expires_at + timedelta(
            seconds=self._upload_completion_grace_seconds
        )
        if datetime.now(UTC) > deadline:
            self._fail(stored_file, "FILE_UPLOAD_EXPIRED")
            self._delete_best_effort(upload_location, context=trusted, file_id=file_id)
            session.flush()
            return CompletionOutcome(
                stored_file=None,
                problem_code="FILE_UPLOAD_EXPIRED",
                problem_detail="The upload completion window has expired.",
            )

        try:
            upload_head = self._storage.head_object(location=upload_location)
        except ObjectStorageOperationError as error:
            raise FileStorageUnavailableError from error
        if upload_head is None:
            return CompletionOutcome(
                stored_file=None,
                problem_code="UPLOAD_NOT_READY",
                problem_detail="The uploaded object is not available yet.",
            )
        if not self._head_matches(upload_head, stored_file):
            self._fail(stored_file, "FILE_UPLOAD_INTEGRITY_MISMATCH")
            self._delete_best_effort(upload_location, context=trusted, file_id=file_id)
            session.flush()
            return CompletionOutcome(
                stored_file=None,
                problem_code="FILE_UPLOAD_FAILED",
                problem_detail="The uploaded object did not pass integrity verification.",
            )

        try:
            final_head = self._storage.head_object(location=storage_location)
            if final_head is None:
                self._storage.copy_object(
                    source=upload_location,
                    destination=storage_location,
                    content_type=stored_file.mime_type,
                    checksum_sha256=stored_file.checksum_sha256,
                )
                final_head = self._storage.head_object(location=storage_location)
        except ObjectStorageOperationError as error:
            raise FileStorageUnavailableError from error
        if final_head is None or not self._head_matches(final_head, stored_file):
            self._fail(stored_file, "FILE_CANONICAL_INTEGRITY_MISMATCH")
            self._delete_best_effort(storage_location, context=trusted, file_id=file_id)
            session.flush()
            return CompletionOutcome(
                stored_file=None,
                problem_code="FILE_UPLOAD_FAILED",
                problem_detail="Privexa could not verify the canonical stored object.",
            )

        stored_file.status = StoredFileStatus.AVAILABLE
        stored_file.object_etag = final_head.etag
        stored_file.completed_at = datetime.now(UTC)
        stored_file.failure_code = None
        session.flush()
        self._delete_best_effort(upload_location, context=trusted, file_id=file_id)
        self._log(
            "file.upload_completed",
            context=trusted.with_minimum_sensitivity(stored_file.sensitivity_level),
            file_id=file_id,
            status=stored_file.status.value,
        )
        return CompletionOutcome(stored_file=stored_file)

    def create_download(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        file_id: UUID,
    ) -> SignedStorageOperation:
        trusted = self._context(session, context, Permission.FILE_READ)
        stored_file = StoredFileRepository.get(
            session,
            context=trusted.to_client_context(),
            file_id=file_id,
        )
        if stored_file is None:
            self._raise_resource_unavailable(
                context=trusted,
                file_id=file_id,
                operation="create_download",
            )
        if stored_file.status != StoredFileStatus.AVAILABLE:
            raise FileStateConflictError(
                code="FILE_NOT_AVAILABLE",
                detail="The file is not available for download.",
            )
        effective_context = trusted.with_minimum_sensitivity(stored_file.sensitivity_level)
        _, storage_location = self._locations(stored_file)
        try:
            head = self._storage.head_object(location=storage_location)
            if head is None or not self._head_matches(head, stored_file):
                raise FileStateConflictError(
                    code="FILE_OBJECT_UNAVAILABLE",
                    detail="The stored object could not be verified.",
                )
            expires_at = datetime.now(UTC) + timedelta(seconds=self._download_ttl_seconds)
            download = self._storage.create_download_url(
                location=storage_location,
                content_type=stored_file.mime_type,
                content_disposition=build_content_disposition(stored_file.original_filename),
                expires_at=expires_at,
                ttl_seconds=self._download_ttl_seconds,
            )
        except ObjectStorageOperationError as error:
            raise FileStorageUnavailableError from error
        self._log(
            "file.download_url_issued",
            context=effective_context,
            file_id=file_id,
            status=stored_file.status.value,
        )
        return download

    def delete(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        file_id: UUID,
    ) -> None:
        trusted = self._context(session, context, Permission.FILE_DELETE)
        stored_file = StoredFileRepository.get(
            session,
            context=trusted.to_client_context(),
            file_id=file_id,
            for_update=True,
        )
        if stored_file is None:
            self._raise_resource_unavailable(
                context=trusted,
                file_id=file_id,
                operation="delete",
            )
        if stored_file.status == StoredFileStatus.DELETED:
            return
        upload_location, storage_location = self._locations(stored_file)
        self._log(
            "file.delete_requested",
            context=trusted,
            file_id=file_id,
            status=stored_file.status.value,
        )
        try:
            self._storage.delete_object(location=storage_location)
            self._storage.delete_object(location=upload_location)
        except ObjectStorageOperationError as error:
            raise FileStorageUnavailableError from error
        stored_file.status = StoredFileStatus.DELETED
        stored_file.deleted_at = datetime.now(UTC)
        stored_file.failure_code = None
        session.flush()
        self._log(
            "file.deleted",
            context=trusted,
            file_id=file_id,
            status=stored_file.status.value,
        )

    @staticmethod
    def _fail(stored_file: StoredFile, failure_code: str) -> None:
        stored_file.status = StoredFileStatus.FAILED
        stored_file.failure_code = failure_code

    def _delete_best_effort(
        self,
        location: ObjectLocation,
        *,
        context: ExecutionContext,
        file_id: UUID,
    ) -> None:
        try:
            self._storage.delete_object(location=location)
        except ObjectStorageOperationError:
            self._log(
                "file.storage_cleanup_failed",
                context=context,
                file_id=file_id,
            )
