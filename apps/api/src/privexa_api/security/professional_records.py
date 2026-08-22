from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.domain.errors import (
    DomainValidationError,
    DomainVersionConflictError,
    TenantOwnershipMismatchError,
)
from privexa_api.domain.events import AggregateType, DomainEvent, EventType
from privexa_api.security.enums import OriginatingChannel
from privexa_api.security.execution_context import (
    TraceId,
    require_trusted_execution_context,
)

_TRUSTED_PROFESSIONAL_AUTHORITY = object()


class ProfessionalRecordOperation(StrEnum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    ARCHIVE = "ARCHIVE"


_PERMISSION_ACTIONS_BY_OPERATION = {
    ProfessionalRecordOperation.CREATE: frozenset({"create"}),
    ProfessionalRecordOperation.UPDATE: frozenset({"update", "manage"}),
    ProfessionalRecordOperation.ARCHIVE: frozenset({"archive"}),
}


class OwnedVersionedRecord(Protocol):
    firm_id: UUID
    client_id: UUID
    version: int


@dataclass(frozen=True, slots=True)
class ProfessionalRecordAuthority:
    """Action-bound ownership and provenance derived from trusted authorization context."""

    request_id: UUID
    trace_id: TraceId | None
    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    client_id: UUID
    originating_channel: OriginatingChannel
    capability: Permission
    operation: ProfessionalRecordOperation
    _issuance_marker: object | None = field(default=None, init=False, repr=False, compare=False)

    def _require_trusted(self) -> None:
        if self._issuance_marker is not _TRUSTED_PROFESSIONAL_AUTHORITY:
            raise DomainValidationError(code="INVALID_PROFESSIONAL_AUTHORITY")

    def _require_operation(self, operation: ProfessionalRecordOperation) -> None:
        self._require_trusted()
        if self.operation is not operation:
            raise DomainValidationError(code="PROFESSIONAL_AUTHORITY_OPERATION_MISMATCH")

    def creation_values(self) -> dict[str, UUID]:
        self._require_operation(ProfessionalRecordOperation.CREATE)
        return {
            "firm_id": self.firm_id,
            "client_id": self.client_id,
            "created_by_membership_id": self.membership_id,
            "updated_by_membership_id": self.membership_id,
        }

    def require_record(
        self,
        record: OwnedVersionedRecord,
        *,
        expected_version: int | None = None,
    ) -> None:
        self._require_trusted()
        if record.firm_id != self.firm_id or record.client_id != self.client_id:
            raise TenantOwnershipMismatchError()
        if expected_version is not None:
            if expected_version < 1:
                raise DomainValidationError(code="INVALID_EXPECTED_VERSION")
            if record.version != expected_version:
                raise DomainVersionConflictError()

    def update_values(
        self,
        record: OwnedVersionedRecord,
        *,
        expected_version: int,
    ) -> dict[str, UUID]:
        self._require_operation(ProfessionalRecordOperation.UPDATE)
        self.require_record(record, expected_version=expected_version)
        return {"updated_by_membership_id": self.membership_id}

    def archive_values(
        self,
        record: OwnedVersionedRecord,
        *,
        expected_version: int,
        archived_at: datetime | None = None,
    ) -> dict[str, UUID | datetime]:
        self._require_operation(ProfessionalRecordOperation.ARCHIVE)
        self.require_record(record, expected_version=expected_version)
        effective_archived_at = archived_at or datetime.now(UTC)
        if effective_archived_at.tzinfo is None or effective_archived_at.utcoffset() is None:
            raise DomainValidationError(code="ARCHIVE_TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
        return {
            "updated_by_membership_id": self.membership_id,
            "archived_at": effective_archived_at.astimezone(UTC),
            "archived_by_membership_id": self.membership_id,
        }

    def event(
        self,
        *,
        event_type: EventType,
        aggregate_type: AggregateType,
        aggregate_id: UUID,
        payload: dict[str, JsonValue] | None = None,
        schema_version: int = 1,
    ) -> DomainEvent:
        self._require_trusted()
        return DomainEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            firm_id=self.firm_id,
            client_id=self.client_id,
            actor_user_id=self.user_id,
            actor_membership_id=self.membership_id,
            request_id=self.request_id,
            trace_id=self.trace_id,
            originating_channel=self.originating_channel.value,
            schema_version=schema_version,
            payload=payload or {},
        )


def issue_professional_record_authority(
    context: object,
    *,
    capability: Permission,
    operation: ProfessionalRecordOperation,
) -> ProfessionalRecordAuthority:
    """Derive record ownership/provenance only after action-specific authorization succeeds."""

    trusted = require_trusted_execution_context(context)
    trusted.require_capability(capability)
    if not isinstance(operation, ProfessionalRecordOperation):
        raise AuthorizationDeniedError(
            reason=AuthorizationFailureReason.INVALID_CONTEXT,
            permission=capability,
        )
    permission_action = capability.value.rsplit(".", maxsplit=1)[-1]
    if permission_action not in _PERMISSION_ACTIONS_BY_OPERATION.get(operation, frozenset()):
        raise AuthorizationDeniedError(
            reason=AuthorizationFailureReason.PERMISSION_DENIED,
            permission=capability,
        )
    if trusted.authorization_scope is not AuthorizationScope.CLIENT or trusted.client_id is None:
        raise DomainValidationError(code="PROFESSIONAL_RECORD_REQUIRES_CLIENT_SCOPE")
    authority = ProfessionalRecordAuthority(
        request_id=trusted.request_id,
        trace_id=trusted.trace_id,
        user_id=trusted.user_id,
        membership_id=trusted.membership_id,
        firm_id=trusted.firm_id,
        client_id=trusted.client_id,
        originating_channel=trusted.originating_channel,
        capability=capability,
        operation=operation,
    )
    object.__setattr__(authority, "_issuance_marker", _TRUSTED_PROFESSIONAL_AUTHORITY)
    return authority
