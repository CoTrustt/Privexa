from __future__ import annotations

from collections.abc import Collection
from uuid import UUID

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationResourceNotFoundError
from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.security.execution_context import ExecutionContext


def require_requested_client_matches_context(
    context: ExecutionContext,
    *,
    requested_client_id: UUID,
    permission: Permission,
) -> ExecutionContext:
    """Bind a client-scoped request target to server-issued active-client authority."""

    context.require_capability(permission)
    if (
        context.authorization_scope != AuthorizationScope.CLIENT
        or context.client_id is None
        or context.client_id != requested_client_id
    ):
        raise AuthorizationResourceNotFoundError(
            reason=AuthorizationFailureReason.RESOURCE_SCOPE_MISMATCH,
            permission=permission,
        )
    return context


def require_exact_resource_ids(
    *,
    requested_ids: Collection[UUID],
    resolved_ids: Collection[UUID],
    permission: Permission,
) -> None:
    """Require every requested resource to resolve exactly once in the trusted scope."""

    requested = tuple(requested_ids)
    if len(requested) != len(set(requested)) or set(requested) != set(resolved_ids):
        raise AuthorizationResourceNotFoundError(
            reason=AuthorizationFailureReason.RESOURCE_SCOPE_MISMATCH,
            permission=permission,
        )
