from __future__ import annotations

from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from privexa_api.api.errors import problem_response

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class CookieCsrfMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, trusted_origin: str, session_cookie_name: str) -> None:
        super().__init__(app)
        self._trusted_origin = trusted_origin.rstrip("/")
        self._session_cookie_name = session_cookie_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        has_session_cookie = self._session_cookie_name in request.cookies
        if request.method in _UNSAFE_METHODS and has_session_cookie:
            origin = request.headers.get("Origin")
            if origin != self._trusted_origin:
                return problem_response(
                    request,
                    status_code=403,
                    code="CSRF_VALIDATION_FAILED",
                    title="Request could not be verified",
                    detail="Refresh Privexa and try again.",
                )
        return await call_next(request)
