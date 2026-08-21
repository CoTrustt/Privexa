from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, ConfigDict

from privexa_api.access_control.enums import FirmRole
from privexa_api.api.dependencies import (
    AuthenticatedIdentityDependency,
    get_stytch_gateway,
    log_authentication_event,
)
from privexa_api.authentication.stytch_gateway import StytchSessionGateway

router = APIRouter(prefix="/auth", tags=["authentication"])


class AuthenticatedSessionResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    user_id: UUID
    membership_id: UUID
    firm_id: UUID
    role: FirmRole
    display_name: str
    firm_name: str


@router.get("/session", response_model=AuthenticatedSessionResponse)
def get_authenticated_session(
    identity: AuthenticatedIdentityDependency,
    response: Response,
) -> AuthenticatedSessionResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return AuthenticatedSessionResponse(
        user_id=identity.principal.user_id,
        membership_id=identity.principal.membership_id,
        firm_id=identity.principal.firm_id,
        role=identity.principal.role,
        display_name=identity.display_name,
        firm_name=identity.firm_name,
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    gateway: Annotated[StytchSessionGateway, Depends(get_stytch_gateway)],
    stytch_session: Annotated[str | None, Cookie(alias="stytch_session")] = None,
) -> None:
    if stytch_session:
        gateway.revoke(stytch_session)

    settings = request.app.state.settings
    for cookie_name in (
        "stytch_session",
        "stytch_session_jwt",
        "stytch_intermediate_session_token",
    ):
        response.delete_cookie(
            cookie_name,
            path="/",
            domain=settings.auth_cookie_domain,
            secure=settings.auth_cookie_secure,
            httponly=True,
            samesite="lax",
        )
    log_authentication_event(
        "authentication.logout_completed",
        request,
        session_was_present=bool(stytch_session),
    )
    response.headers["Cache-Control"] = "no-store"
