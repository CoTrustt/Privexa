from __future__ import annotations

from sqlalchemy.orm import Session

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationResourceNotFoundError
from privexa_api.access_control.permissions import Permission
from privexa_api.clients.models import ClientWorkspace
from privexa_api.clients.repository import ClientWorkspaceRepository
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.security.execution_context import (
    ExecutionContext,
    require_trusted_execution_context,
)


class ClientWorkspaceService:
    """Application boundary demonstrating mandatory action and tenant authorization."""

    @staticmethod
    def get_current(
        session: Session,
        *,
        context: ExecutionContext,
    ) -> ClientWorkspace:
        trusted_context = require_trusted_execution_context(context)
        trusted_context.require_capability(Permission.CLIENT_READ)
        require_matching_execution_context_scope(session, trusted_context)
        client = ClientWorkspaceRepository.get_active(
            session,
            context=trusted_context.to_client_context(),
        )
        if client is None:
            raise AuthorizationResourceNotFoundError(
                reason=AuthorizationFailureReason.RESOURCE_SCOPE_MISMATCH,
                permission=Permission.CLIENT_READ,
            )
        return client
