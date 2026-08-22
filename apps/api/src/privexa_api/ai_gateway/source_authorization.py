from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.access_control.permissions import Permission
from privexa_api.ai_gateway.contracts import AISourceReference
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.db.errors import DatabaseSecurityError
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.files.enums import StoredFileStatus
from privexa_api.files.models import StoredFile
from privexa_api.security.client_boundary import require_exact_resource_ids
from privexa_api.security.execution_context import ExecutionContext


class AISourceAuthorizationFailure(StrEnum):
    SOURCE_TYPE_NOT_ALLOWED = "SOURCE_TYPE_NOT_ALLOWED"
    DUPLICATE_SOURCE = "DUPLICATE_SOURCE"
    SOURCE_RESOLVER_UNAVAILABLE = "SOURCE_RESOLVER_UNAVAILABLE"
    DATABASE_SESSION_REQUIRED = "DATABASE_SESSION_REQUIRED"
    SOURCE_PERMISSION_DENIED = "SOURCE_PERMISSION_DENIED"
    RESOURCE_SCOPE_MISMATCH = "RESOURCE_SCOPE_MISMATCH"


class AISourceAuthorizationError(Exception):
    def __init__(
        self,
        *,
        category: AIErrorCategory,
        reason: AISourceAuthorizationFailure,
        attempted_count: int,
    ) -> None:
        super().__init__(reason.value)
        self.category = category
        self.reason = reason
        self.attempted_count = attempted_count


class AISourceResolver(Protocol):
    source_type: str
    required_permission: Permission

    def resolve_authorized_ids(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        source_ids: Sequence[UUID],
    ) -> frozenset[UUID]: ...


class StoredFileSourceResolver:
    source_type = "stored_file"
    required_permission = Permission.FILE_READ

    def resolve_authorized_ids(
        self,
        session: Session,
        *,
        context: ExecutionContext,
        source_ids: Sequence[UUID],
    ) -> frozenset[UUID]:
        context.require_capability(self.required_permission)
        require_matching_execution_context_scope(session, context)
        return frozenset(
            session.scalars(
                select(StoredFile.id).where(
                    StoredFile.id.in_(source_ids),
                    StoredFile.firm_id == context.firm_id,
                    StoredFile.client_id == context.client_id,
                    StoredFile.status == StoredFileStatus.AVAILABLE,
                )
            )
        )


class AISourceAuthorizer:
    """Resolve every declared source inside trusted tenant scope before model execution."""

    def __init__(self, resolvers: Iterable[AISourceResolver] = ()) -> None:
        resolver_values = tuple(resolvers)
        by_type = {resolver.source_type: resolver for resolver in resolver_values}
        if len(by_type) != len(resolver_values):
            raise ValueError("AI source resolver types must be unique")
        self._resolvers = MappingProxyType(by_type)

    def authorize(
        self,
        *,
        session: Session | None,
        context: ExecutionContext,
        allowed_source_types: frozenset[str],
        source_references: Sequence[AISourceReference],
    ) -> tuple[AISourceReference, ...]:
        references = tuple(source_references)
        if not references:
            return ()
        keys = tuple((reference.source_type, reference.source_id) for reference in references)
        if len(keys) != len(set(keys)):
            raise AISourceAuthorizationError(
                category=AIErrorCategory.INVALID_INPUT,
                reason=AISourceAuthorizationFailure.DUPLICATE_SOURCE,
                attempted_count=len(references),
            )
        if any(reference.source_type not in allowed_source_types for reference in references):
            raise AISourceAuthorizationError(
                category=AIErrorCategory.INVALID_INPUT,
                reason=AISourceAuthorizationFailure.SOURCE_TYPE_NOT_ALLOWED,
                attempted_count=len(references),
            )
        if session is None:
            raise AISourceAuthorizationError(
                category=AIErrorCategory.CONFIGURATION_ERROR,
                reason=AISourceAuthorizationFailure.DATABASE_SESSION_REQUIRED,
                attempted_count=len(references),
            )
        try:
            require_matching_execution_context_scope(session, context)
        except DatabaseSecurityError as error:
            raise AISourceAuthorizationError(
                category=AIErrorCategory.CLIENT_BOUNDARY_VIOLATION,
                reason=AISourceAuthorizationFailure.RESOURCE_SCOPE_MISMATCH,
                attempted_count=len(references),
            ) from error

        references_by_type: dict[str, list[UUID]] = defaultdict(list)
        for reference in references:
            references_by_type[reference.source_type].append(reference.source_id)
        for source_type, source_ids in references_by_type.items():
            resolver = self._resolvers.get(source_type)
            if resolver is None:
                raise AISourceAuthorizationError(
                    category=AIErrorCategory.CONFIGURATION_ERROR,
                    reason=AISourceAuthorizationFailure.SOURCE_RESOLVER_UNAVAILABLE,
                    attempted_count=len(references),
                )
            try:
                context.require_capability(resolver.required_permission)
                resolved_ids = resolver.resolve_authorized_ids(
                    session,
                    context=context,
                    source_ids=source_ids,
                )
                require_exact_resource_ids(
                    requested_ids=source_ids,
                    resolved_ids=resolved_ids,
                    permission=resolver.required_permission,
                )
            except AuthorizationProblem as error:
                reason = (
                    AISourceAuthorizationFailure.SOURCE_PERMISSION_DENIED
                    if error.reason
                    in {
                        AuthorizationFailureReason.INVALID_CONTEXT,
                        AuthorizationFailureReason.PERMISSION_DENIED,
                    }
                    else AISourceAuthorizationFailure.RESOURCE_SCOPE_MISMATCH
                )
                raise AISourceAuthorizationError(
                    category=AIErrorCategory.CLIENT_BOUNDARY_VIOLATION,
                    reason=reason,
                    attempted_count=len(references),
                ) from error
            except DatabaseSecurityError as error:
                raise AISourceAuthorizationError(
                    category=AIErrorCategory.CLIENT_BOUNDARY_VIOLATION,
                    reason=AISourceAuthorizationFailure.RESOURCE_SCOPE_MISMATCH,
                    attempted_count=len(references),
                ) from error
        return references
