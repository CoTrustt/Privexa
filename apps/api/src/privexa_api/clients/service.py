from __future__ import annotations

from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientAuthorizationContext
from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationResourceNotFoundError
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.policy import AuthorizationPolicy
from privexa_api.clients.models import ClientWorkspace
from privexa_api.clients.repository import ClientWorkspaceRepository


class ClientWorkspaceService:
    """Application boundary demonstrating mandatory action and tenant authorization."""

    @staticmethod
    def get_current(
        session: Session,
        *,
        authorization: ClientAuthorizationContext,
    ) -> ClientWorkspace:
        AuthorizationPolicy.require(authorization, Permission.CLIENT_READ)
        client = ClientWorkspaceRepository.get_active(
            session,
            context=authorization.client_context,
        )
        if client is None:
            raise AuthorizationResourceNotFoundError(
                reason=AuthorizationFailureReason.RESOURCE_SCOPE_MISMATCH,
                permission=Permission.CLIENT_READ,
            )
        return client
