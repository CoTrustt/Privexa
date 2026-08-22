from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Annotated

from fastapi import Cookie, Depends, Request
from sqlalchemy.orm import Session

from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.authentication.errors import AuthenticationProblem, AuthenticationRequiredError
from privexa_api.authentication.service import AuthenticatedIdentity, AuthenticationService
from privexa_api.authentication.stytch_gateway import StytchSessionGateway
from privexa_api.db.session import discard_domain_events, drain_domain_events
from privexa_api.domain.telemetry import log_committed_domain_event
from privexa_api.files.service import StoredFileService

LOGGER = logging.getLogger("privexa.authentication")
_AUTHENTICATION_HANDLER_NAME = "privexa-authentication-json"


def configure_authentication_logging() -> None:
    """Keep security events enabled after server or migration logging reconfiguration."""

    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _AUTHENTICATION_HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_AUTHENTICATION_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


def get_database_session(request: Request) -> Iterator[Session]:
    """Provide the one low-level request transaction used for identity bootstrap and scoped work.

    Protected routes must pair this cached dependency with an authentication/authorization
    dependency, which establishes Firm or Client context before domain repositories execute.
    """

    session = request.app.state.session_factory()
    try:
        try:
            with session.begin():
                yield session
        except Exception:
            discard_domain_events(session)
            raise
        else:
            for event in drain_domain_events(session):
                log_committed_domain_event(event)
    finally:
        session.close()


def get_stytch_gateway(request: Request) -> StytchSessionGateway:
    return request.app.state.stytch_gateway


def get_stored_file_service(request: Request) -> StoredFileService:
    return request.app.state.stored_file_service


def get_ai_gateway(request: Request) -> AIGateway:
    return request.app.state.ai_gateway


def log_authentication_event(event: str, request: Request, **fields: object) -> None:
    payload = {"event": event, "request_id": request.state.request_id, **fields}
    LOGGER.info(json.dumps(payload, sort_keys=True, default=str))


def require_authenticated_identity(
    request: Request,
    session: Annotated[Session, Depends(get_database_session)],
    gateway: Annotated[StytchSessionGateway, Depends(get_stytch_gateway)],
    stytch_session: Annotated[str | None, Cookie(alias="stytch_session")] = None,
) -> AuthenticatedIdentity:
    if not stytch_session:
        raise AuthenticationRequiredError

    try:
        validated_session = gateway.authenticate(stytch_session)
        identity = AuthenticationService.resolve_identity(
            session,
            validated_session=validated_session,
        )
    except AuthenticationProblem as error:
        log_authentication_event("authentication.denied", request, reason=error.code)
        raise

    log_authentication_event(
        "authentication.principal_resolved",
        request,
        user_id=identity.principal.user_id,
        membership_id=identity.principal.membership_id,
        firm_id=identity.principal.firm_id,
    )
    return identity


AuthenticatedIdentityDependency = Annotated[
    AuthenticatedIdentity,
    Depends(require_authenticated_identity),
]
