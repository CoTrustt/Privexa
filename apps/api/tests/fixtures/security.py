from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationResourceNotFoundError,
)
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.clients.models import ClientWorkspace


@dataclass(frozen=True, slots=True)
class MockToolCall:
    """Untrusted tool selection and arguments proposed by a future model or agent."""

    tool_name: str
    resource_id: UUID


@dataclass(frozen=True, slots=True)
class MockExecutionContext:
    """Trusted actor and tenant scope supplied by Privexa, never by model output."""

    principal: AuthenticatedPrincipal
    firm_id: UUID
    client_id: UUID


@dataclass(frozen=True, slots=True)
class MockToolResult:
    resource_id: UUID
    name: str


class MockPrivexaToolExecutor:
    """Test contract for a future tool adapter using normal authorization and RLS."""

    _GET_CLIENT_WORKSPACE = "get_client_workspace"

    @classmethod
    def execute(
        cls,
        session: Session,
        *,
        context: MockExecutionContext,
        call: MockToolCall,
    ) -> MockToolResult:
        if not isinstance(context, MockExecutionContext):
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=Permission.CLIENT_READ,
            )
        if context.firm_id != context.principal.firm_id:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.INVALID_CONTEXT,
                permission=Permission.CLIENT_READ,
            )
        if call.tool_name != cls._GET_CLIENT_WORKSPACE:
            raise AuthorizationDeniedError(
                reason=AuthorizationFailureReason.UNKNOWN_PERMISSION,
                permission=Permission.CLIENT_READ,
            )

        AccessControlService.authorize_client(
            session,
            principal=context.principal,
            client_id=context.client_id,
            permission=Permission.CLIENT_READ,
        )
        resource = session.scalar(
            select(ClientWorkspace).where(ClientWorkspace.id == call.resource_id)
        )
        if resource is None:
            raise AuthorizationResourceNotFoundError(
                reason=AuthorizationFailureReason.RESOURCE_SCOPE_MISMATCH,
                permission=Permission.CLIENT_READ,
            )
        return MockToolResult(resource_id=resource.id, name=resource.name)


@dataclass(frozen=True, slots=True)
class MockAgentInvocation:
    """A queued future agent action carrying no live Session or cached authorization."""

    execution_context: MockExecutionContext
    tool_call: MockToolCall


class MockPrivexaAgentExecutor:
    """A minimal agent boundary that delegates all authority to the normal tool path."""

    @staticmethod
    def execute(session: Session, *, invocation: MockAgentInvocation) -> MockToolResult:
        return MockPrivexaToolExecutor.execute(
            session,
            context=invocation.execution_context,
            call=invocation.tool_call,
        )
