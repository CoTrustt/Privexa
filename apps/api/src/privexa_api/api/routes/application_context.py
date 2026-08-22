from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.api.authorization_dependencies import (
    require_firm_permission,
    require_switch_target_client_permission,
)
from privexa_api.api.dependencies import (
    AuthenticatedIdentityDependency,
    get_database_session,
)
from privexa_api.application_context.schemas import (
    ActiveClientResponse,
    ApplicationContextResponse,
)
from privexa_api.application_context.service import ApplicationContextService
from privexa_api.security.execution_context import ExecutionContext

router = APIRouter(prefix="/application-context", tags=["application-context"])

DatabaseSession = Annotated[Session, Depends(get_database_session)]
FirmReadContext = Annotated[
    ExecutionContext,
    Depends(require_firm_permission(Permission.FIRM_READ)),
]
ClientReadContext = Annotated[
    ExecutionContext,
    Depends(require_switch_target_client_permission(Permission.CLIENT_READ)),
]


@router.get("", response_model=ApplicationContextResponse)
def get_application_context(
    response: Response,
    identity: AuthenticatedIdentityDependency,
    context: FirmReadContext,
    session: DatabaseSession,
) -> ApplicationContextResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return ApplicationContextService.get_application_context(
        session,
        identity=identity,
        context=context,
    )


@router.put(
    "/active-client/{client_id}",
    response_model=ActiveClientResponse,
)
def switch_active_client(
    client_id: UUID,
    response: Response,
    identity: AuthenticatedIdentityDependency,
    context: ClientReadContext,
    session: DatabaseSession,
) -> ActiveClientResponse:
    del client_id  # The authorization dependency has validated and bound this path value.
    response.headers["Cache-Control"] = "no-store"
    return ApplicationContextService.switch_active_client(
        session,
        identity=identity,
        context=context,
    )
