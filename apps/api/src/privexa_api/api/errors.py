from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm.exc import StaleDataError

from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationProblem,
    AuthorizationResourceNotFoundError,
)
from privexa_api.application_context.errors import ApplicationContextProblem
from privexa_api.authentication.errors import AuthenticationProblem
from privexa_api.db.errors import DatabaseSecurityError
from privexa_api.domain.errors import DomainProblem, DomainProblemKind, DomainVersionConflictError
from privexa_api.domain.telemetry import LOGGER as DOMAIN_LOGGER
from privexa_api.files.errors import FileProblem

DATABASE_SECURITY_LOGGER = logging.getLogger("privexa.database_security")


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    detail: str
    request_id: UUID


class FieldProblem(BaseModel):
    path: str
    code: str
    message: str


_FIELD_ERROR_CONTRACT = {
    "missing": ("REQUIRED", "This field is required."),
    "extra_forbidden": ("EXTRA_FIELD", "This field is not accepted."),
    "json_invalid": ("INVALID_JSON", "The request body is not valid JSON."),
}
_MAX_FIELD_ERRORS = 50


def _safe_validation_path(location: object, *, error_type: str) -> str:
    if not isinstance(location, (tuple, list)):
        return "request"
    # Pydantic locations can include caller-controlled keys inside mappings. The request scope and
    # top-level schema field are enough for a useful response without reflecting nested keys.
    parts = list(location[:2])
    if error_type == "extra_forbidden" and len(parts) > 1:
        # The final component is caller-controlled for forbidden extra fields.
        parts.pop()
    safe_parts = [
        str(part)
        for part in parts
        if isinstance(part, int) or (isinstance(part, str) and part.replace("_", "").isalnum())
    ]
    return ".".join(safe_parts) or "request"


def request_validation_problem_handler(
    request: Request,
    error: RequestValidationError,
) -> JSONResponse:
    field_errors: list[FieldProblem] = []
    for item in error.errors()[:_MAX_FIELD_ERRORS]:
        raw_type = str(item.get("type", ""))
        code, message = _FIELD_ERROR_CONTRACT.get(
            raw_type,
            ("INVALID_VALUE", "This field value is not valid."),
        )
        path = _safe_validation_path(item.get("loc", ()), error_type=raw_type)
        field_errors.append(FieldProblem(path=path, code=code, message=message))

    problem = ProblemDetail(
        title="Request validation failed",
        status=422,
        code="REQUEST_VALIDATION_FAILED",
        detail="One or more request fields are invalid.",
        request_id=request.state.request_id,
    )
    content = problem.model_dump(mode="json")
    content["field_errors"] = [field.model_dump(mode="json") for field in field_errors]
    return JSONResponse(
        status_code=422,
        content=content,
        headers={"Cache-Control": "no-store"},
    )


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


_DOMAIN_STATUS_CODES = {
    DomainProblemKind.VALIDATION: 422,
    DomainProblemKind.NOT_FOUND: 404,
    DomainProblemKind.LIFECYCLE_CONFLICT: 409,
    DomainProblemKind.VERSION_CONFLICT: 409,
    DomainProblemKind.INTEGRITY_CONFLICT: 409,
}


def domain_problem_handler(request: Request, error: DomainProblem) -> JSONResponse:
    status_code = _DOMAIN_STATUS_CODES[error.kind]
    DOMAIN_LOGGER.info(
        json.dumps(
            {
                "event": "domain.operation_rejected",
                "request_id": request.state.request_id,
                "reason_code": error.diagnostic_code,
                "status": status_code,
            },
            sort_keys=True,
            default=str,
        )
    )
    problem = ProblemDetail(
        title=error.title,
        status=status_code,
        code=error.code,
        detail=error.detail,
        request_id=request.state.request_id,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


def stale_data_problem_handler(request: Request, _error: StaleDataError) -> JSONResponse:
    return domain_problem_handler(request, DomainVersionConflictError())


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
