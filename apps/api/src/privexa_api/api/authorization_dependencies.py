from __future__ import annotations

import json
import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from privexa_api.access_control.context import AuthorizationContext
from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.api.dependencies import (
    AuthenticatedIdentityDependency,
    get_database_session,
)
from privexa_api.application_context.errors import ActiveClientRequiredError
from privexa_api.application_context.repository import ApplicationContextRepository
from privexa_api.application_context.service import session_fingerprint
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.observability.tracing import current_trace_correlation
from privexa_api.security.client_boundary import require_requested_client_matches_context
from privexa_api.security.enums import OriginatingChannel
from privexa_api.security.execution_context import ExecutionContext, issue_execution_context
from privexa_api.security.sensitivity import DEFAULT_SENSITIVITY

LOGGER = logging.getLogger("privexa.authorization")
_AUTHORIZATION_HANDLER_NAME = "privexa-authorization-json"


class RouteProtectionClass(StrEnum):
    FIRM = "FIRM"
    SELF = "SELF"
    SWITCH_TARGET_CLIENT = "SWITCH_TARGET_CLIENT"
    ACTIVE_CLIENT = "ACTIVE_CLIENT"
    ACTIVE_CLIENT_PATH = "ACTIVE_CLIENT_PATH"


def _classify_dependency(
    dependency: Callable[..., ExecutionContext],
    protection_class: RouteProtectionClass,
) -> Callable[..., ExecutionContext]:
    dependency.__dict__["__privexa_protection_class__"] = protection_class
    return dependency


def configure_authorization_logging() -> None:
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _AUTHORIZATION_HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_AUTHORIZATION_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


def _log_denial(
    *,
    request: Request,
    identity: AuthenticatedIdentityDependency,
    error: AuthorizationProblem,
    permission: Permission,
    client_id: UUID | None = None,
    requested_client_id: UUID | None = None,
) -> None:
    payload = {
        "event": "authorization.denied",
        "request_id": request.state.request_id,
        "principal_id": identity.principal.user_id,
        "membership_id": identity.principal.membership_id,
        "firm_id": identity.principal.firm_id,
        "client_id": client_id,
        "permission": permission.value,
        "decision": "DENY",
        "reason_code": error.reason.value,
    }
    if requested_client_id is not None:
        payload["requested_client_id"] = requested_client_id
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def _log_context_established(
    *,
    context: ExecutionContext,
    permission: Permission,
) -> None:
    payload = {
        "event": "authorization.context_established",
        **context.safe_logging_fields(),
        "permission": permission.value,
        "decision": "ALLOW",
    }
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def _create_execution_context(
    *,
    request: Request,
    session: Session,
    authorization: AuthorizationContext,
) -> ExecutionContext:
    context = issue_execution_context(
        authorization=authorization,
        request_id=request.state.request_id,
        trace_id=current_trace_correlation().trace_id,
        effective_sensitivity=DEFAULT_SENSITIVITY,
        originating_channel=OriginatingChannel.WEB,
    )
    require_matching_execution_context_scope(session, context)
    return context


def require_firm_permission(
    permission: Permission,
) -> Callable[..., ExecutionContext]:
    def dependency(
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> ExecutionContext:
        try:
            authorization = AccessControlService.authorize_firm(
                session,
                principal=identity.principal,
                permission=permission,
            )
        except AuthorizationProblem as error:
            _log_denial(
                request=request,
                identity=identity,
                error=error,
                permission=permission,
            )
            raise
        context = _create_execution_context(
            request=request,
            session=session,
            authorization=authorization,
        )
        _log_context_established(context=context, permission=permission)
        return context

    return _classify_dependency(dependency, RouteProtectionClass.FIRM)


def require_switch_target_client_permission(
    permission: Permission,
) -> Callable[..., ExecutionContext]:
    """Authorize an explicit client target for the active-client switch operation."""

    def dependency(
        client_id: UUID,
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> ExecutionContext:
        try:
            authorization = AccessControlService.authorize_client(
                session,
                principal=identity.principal,
                client_id=client_id,
                permission=permission,
            )
        except AuthorizationProblem as error:
            _log_denial(
                request=request,
                identity=identity,
                error=error,
                permission=permission,
                client_id=client_id,
            )
            raise
        context = _create_execution_context(
            request=request,
            session=session,
            authorization=authorization,
        )
        _log_context_established(context=context, permission=permission)
        return context

    return _classify_dependency(dependency, RouteProtectionClass.SWITCH_TARGET_CLIENT)


def require_self_permission(
    permission: Permission,
) -> Callable[..., ExecutionContext]:
    def dependency(
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> ExecutionContext:
        try:
            authorization = AccessControlService.authorize_self(
                session,
                principal=identity.principal,
                permission=permission,
            )
        except AuthorizationProblem as error:
            _log_denial(
                request=request,
                identity=identity,
                error=error,
                permission=permission,
            )
            raise
        context = _create_execution_context(
            request=request,
            session=session,
            authorization=authorization,
        )
        _log_context_established(context=context, permission=permission)
        return context

    return _classify_dependency(dependency, RouteProtectionClass.SELF)


def require_active_client_permission(
    permission: Permission,
) -> Callable[..., ExecutionContext]:
    """Authorize the active client selected for the validated provider session."""

    def dependency(
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> ExecutionContext:
        client_id = ApplicationContextRepository.find_active_client_id(
            session,
            firm_id=identity.principal.firm_id,
            membership_id=identity.principal.membership_id,
            session_fingerprint=session_fingerprint(identity.principal.stytch_member_session_id),
        )
        if client_id is None:
            raise ActiveClientRequiredError
        try:
            authorization = AccessControlService.authorize_client(
                session,
                principal=identity.principal,
                client_id=client_id,
                permission=permission,
            )
        except AuthorizationProblem as error:
            _log_denial(
                request=request,
                identity=identity,
                error=error,
                permission=permission,
                client_id=client_id,
            )
            raise
        context = _create_execution_context(
            request=request,
            session=session,
            authorization=authorization,
        )
        _log_context_established(context=context, permission=permission)
        return context

    return _classify_dependency(dependency, RouteProtectionClass.ACTIVE_CLIENT)


def require_active_client_path_permission(
    permission: Permission,
) -> Callable[..., ExecutionContext]:
    """Authorize the server-selected active client and bind it to the path target."""

    active_client_dependency = require_active_client_permission(permission)

    def dependency(
        client_id: UUID,
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> ExecutionContext:
        context = active_client_dependency(request=request, identity=identity, session=session)
        try:
            return require_requested_client_matches_context(
                context,
                requested_client_id=client_id,
                permission=permission,
            )
        except AuthorizationProblem as error:
            _log_denial(
                request=request,
                identity=identity,
                error=error,
                permission=permission,
                client_id=context.client_id,
                requested_client_id=client_id,
            )
            raise

    return _classify_dependency(dependency, RouteProtectionClass.ACTIVE_CLIENT_PATH)
