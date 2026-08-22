from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError

from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationProblem,
    AuthorizationResourceNotFoundError,
)
from privexa_api.application_context.errors import ApplicationContextProblem
from privexa_api.authentication.errors import AuthenticationProblem
from privexa_api.db.errors import DatabaseSecurityError
from privexa_api.files.errors import FileProblem

DATABASE_SECURITY_LOGGER = logging.getLogger("privexa.database_security")


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    request_id: UUID


def authentication_problem_handler(
    request: Request,
    error: AuthenticationProblem,
) -> JSONResponse:
    problem = ProblemDetail(
        title=error.title,
        status=error.status_code,
        code=error.code,
        detail=error.detail,
        request_id=request.state.request_id,
    )
    headers: dict[str, str] = {"Cache-Control": "no-store"}
    if error.status_code == 401:
        headers["WWW-Authenticate"] = "Session"
    return JSONResponse(
        status_code=error.status_code,
        content=problem.model_dump(mode="json"),
        headers=headers,
    )


def authorization_problem_handler(
    request: Request,
    error: AuthorizationProblem,
) -> JSONResponse:
    if isinstance(error, AuthorizationResourceNotFoundError):
        status_code = 404
        code = "RESOURCE_NOT_FOUND"
        title = "Resource not found"
        detail = "The requested resource could not be found."
    elif isinstance(error, AuthorizationDeniedError):
        status_code = 403
        code = "FORBIDDEN"
        title = "Action not permitted"
        detail = "You do not have permission to perform this action."
    else:
        status_code = 403
        code = "FORBIDDEN"
        title = "Action not permitted"
        detail = "You do not have permission to perform this action."

    problem = ProblemDetail(
        title=title,
        status=status_code,
        code=code,
        detail=detail,
        request_id=request.state.request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def database_security_problem_handler(
    request: Request,
    error: DatabaseSecurityError,
) -> JSONResponse:
    DATABASE_SECURITY_LOGGER.error(
        json.dumps(
            {
                "event": "database.security_context_failed",
                "request_id": request.state.request_id,
                "firm_id": error.firm_id,
                "client_id": error.client_id,
                "reason_code": error.code,
            },
            sort_keys=True,
            default=str,
        )
    )
    problem = ProblemDetail(
        title="Secure database context unavailable",
        status=500,
        code="DATABASE_SECURITY_CONTEXT_UNAVAILABLE",
        detail="Privexa could not safely complete this request.",
        request_id=request.state.request_id,
    )
    return JSONResponse(
        status_code=500,
        content=problem.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def database_operation_problem_handler(
    request: Request,
    error: DBAPIError,
) -> JSONResponse:
    sqlstate = getattr(error.orig, "sqlstate", None)
    policy_denied = sqlstate == "42501"
    DATABASE_SECURITY_LOGGER.error(
        json.dumps(
            {
                "event": (
                    "database.operation_denied" if policy_denied else "database.operation_failed"
                ),
                "request_id": request.state.request_id,
                "sqlstate": sqlstate,
            },
            sort_keys=True,
            default=str,
        )
    )
    problem = ProblemDetail(
        title="Action not permitted" if policy_denied else "Database operation failed",
        status=403 if policy_denied else 500,
        code="FORBIDDEN" if policy_denied else "DATABASE_OPERATION_FAILED",
        detail=(
            "You do not have permission to perform this action."
            if policy_denied
            else "Privexa could not safely complete this request."
        ),
        request_id=request.state.request_id,
    )
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def file_problem_handler(request: Request, error: FileProblem) -> JSONResponse:
    problem = ProblemDetail(
        title=error.title,
        status=error.status_code,
        code=error.code,
        detail=error.detail,
        request_id=request.state.request_id,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=problem.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def application_context_problem_handler(
    request: Request,
    error: ApplicationContextProblem,
) -> JSONResponse:
    problem = ProblemDetail(
        title=error.title,
        status=error.status_code,
        code=error.code,
        detail=error.detail,
        request_id=request.state.request_id,
    )
    return JSONResponse(
        status_code=error.status_code,
        content=problem.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    title: str,
    detail: str,
) -> JSONResponse:
    content: dict[str, Any] = ProblemDetail(
        title=title,
        status=status_code,
        code=code,
        detail=detail,
        request_id=request.state.request_id,
    ).model_dump(mode="json")
    return JSONResponse(
        status_code=status_code,
        content=content,
        headers={"Cache-Control": "no-store"},
    )
