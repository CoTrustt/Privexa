from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy.orm import Session

from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import Permission
from privexa_api.application_context.repository import ApplicationContextRepository
from privexa_api.application_context.schemas import (
    ActiveClientResponse,
    ApplicationContextResponse,
    ApplicationContextState,
    ClientSummary,
    FirmSummary,
    UserSummary,
)
from privexa_api.authentication.service import AuthenticatedIdentity
from privexa_api.clients.service import ClientWorkspaceService
from privexa_api.security.execution_context import (
    ExecutionContext,
    require_trusted_execution_context,
)

LOGGER = logging.getLogger("privexa.application_context")
_HANDLER_NAME = "privexa-application-context-json"


def configure_application_context_logging() -> None:
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


def session_fingerprint(member_session_id: str) -> str:
    """Fingerprint a validated provider session without persisting its identifier."""

    return hashlib.sha256(member_session_id.encode("utf-8")).hexdigest()


def _require_identity_matches_context(
    identity: AuthenticatedIdentity,
    context: ExecutionContext,
) -> None:
    trusted_context = require_trusted_execution_context(context)
    principal = identity.principal
    if (
        principal.user_id != trusted_context.user_id
        or principal.membership_id != trusted_context.membership_id
        or principal.firm_id != trusted_context.firm_id
    ):
        raise AuthorizationDeniedError(reason=AuthorizationFailureReason.INVALID_CONTEXT)


class ApplicationContextService:
    @staticmethod
    def get_application_context(
        session: Session,
        *,
        identity: AuthenticatedIdentity,
        context: ExecutionContext,
    ) -> ApplicationContextResponse:
        trusted_context = require_trusted_execution_context(context)
        trusted_context.require_capability(Permission.FIRM_READ)
        _require_identity_matches_context(identity, trusted_context)

        clients = [
            ClientSummary(id=record.client_id, display_name=record.display_name)
            for record in ApplicationContextRepository.list_authorized_active_clients(session)
        ]
        active_client_id = ApplicationContextRepository.find_active_client_id(
            session,
            firm_id=trusted_context.firm_id,
            membership_id=trusted_context.membership_id,
            session_fingerprint=session_fingerprint(identity.principal.stytch_member_session_id),
        )
        active_client = next(
            (client for client in clients if client.id == active_client_id),
            None,
        )
        if not clients:
            state = ApplicationContextState.NO_AUTHORISED_CLIENTS
        elif active_client is None:
            state = ApplicationContextState.CLIENT_SELECTION_REQUIRED
        else:
            state = ApplicationContextState.ACTIVE_CLIENT

        return ApplicationContextResponse(
            state=state,
            user=UserSummary(
                id=trusted_context.user_id,
                display_name=identity.display_name,
            ),
            firm=FirmSummary(
                id=trusted_context.firm_id,
                display_name=identity.firm_name,
            ),
            active_client=active_client,
            authorised_clients=clients,
        )

    @staticmethod
    def switch_active_client(
        session: Session,
        *,
        identity: AuthenticatedIdentity,
        context: ExecutionContext,
    ) -> ActiveClientResponse:
        trusted_context = require_trusted_execution_context(context)
        trusted_context.require_capability(Permission.CLIENT_READ)
        _require_identity_matches_context(identity, trusted_context)
        client = ClientWorkspaceService.get_current(session, context=trusted_context)
        previous_client_id = ApplicationContextRepository.set_active_client(
            session,
            firm_id=trusted_context.firm_id,
            membership_id=trusted_context.membership_id,
            client_id=client.id,
            session_fingerprint=session_fingerprint(identity.principal.stytch_member_session_id),
        )
        LOGGER.info(
            json.dumps(
                {
                    "event": "application_context.client_switched",
                    **trusted_context.safe_logging_fields(),
                    "previous_client_id": previous_client_id,
                    "client_id": client.id,
                },
                sort_keys=True,
                default=str,
            )
        )
        return ActiveClientResponse(
            active_client=ClientSummary(id=client.id, display_name=client.name)
        )
