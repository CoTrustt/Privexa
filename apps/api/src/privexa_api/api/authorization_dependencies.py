from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from privexa_api.access_control.context import (
    ClientAuthorizationContext,
    FirmAuthorizationContext,
    SelfAuthorizationContext,
)
from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.api.dependencies import (
    AuthenticatedIdentityDependency,
    get_database_session,
)

LOGGER = logging.getLogger("privexa.authorization")
_AUTHORIZATION_HANDLER_NAME = "privexa-authorization-json"


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
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def _log_context_established(
    *,
    request: Request,
    identity: AuthenticatedIdentityDependency,
    permission: Permission,
    client_id: UUID | None = None,
) -> None:
    payload = {
        "event": "authorization.context_established",
        "request_id": request.state.request_id,
        "principal_id": identity.principal.user_id,
        "membership_id": identity.principal.membership_id,
        "firm_id": identity.principal.firm_id,
        "client_id": client_id,
        "permission": permission.value,
        "decision": "ALLOW",
    }
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def require_firm_permission(
    permission: Permission,
) -> Callable[..., FirmAuthorizationContext]:
    def dependency(
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> FirmAuthorizationContext:
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
        _log_context_established(
            request=request,
            identity=identity,
            permission=permission,
        )
        return authorization

    return dependency


def require_client_permission(
    permission: Permission,
) -> Callable[..., ClientAuthorizationContext]:
    def dependency(
        client_id: UUID,
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> ClientAuthorizationContext:
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
        _log_context_established(
            request=request,
            identity=identity,
            permission=permission,
            client_id=client_id,
        )
        return authorization

    return dependency


def require_self_permission(
    permission: Permission,
) -> Callable[..., SelfAuthorizationContext]:
    def dependency(
        request: Request,
        identity: AuthenticatedIdentityDependency,
        session: Annotated[Session, Depends(get_database_session)],
    ) -> SelfAuthorizationContext:
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
        _log_context_established(
            request=request,
            identity=identity,
            permission=permission,
        )
        return authorization

    return dependency
