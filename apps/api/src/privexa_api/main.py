from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.api.authorization_dependencies import configure_authorization_logging
from privexa_api.api.dependencies import configure_authentication_logging
from privexa_api.api.errors import (
    authentication_problem_handler,
    authorization_problem_handler,
    database_operation_problem_handler,
    database_security_problem_handler,
)
from privexa_api.api.middleware import CookieCsrfMiddleware, RequestContextMiddleware
from privexa_api.api.routes.authentication import router as authentication_router
from privexa_api.authentication.errors import AuthenticationProblem
from privexa_api.authentication.stytch_gateway import (
    StytchB2BSessionGateway,
    StytchSessionGateway,
)
from privexa_api.config import Settings, get_settings
from privexa_api.db import model_registry as _model_registry  # noqa: F401
from privexa_api.db.errors import DatabaseSecurityError
from privexa_api.db.session import (
    build_engine,
    build_session_factory,
    validate_runtime_database_security,
)


def create_app(
    *,
    settings: Settings | None = None,
    stytch_gateway: StytchSessionGateway | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    configure_authentication_logging()
    configure_authorization_logging()
    application_settings = settings or get_settings()
    managed_engine = None
    if session_factory is None:
        managed_engine = build_engine(application_settings.app_database_url)
        session_factory = build_session_factory(managed_engine)
    if stytch_gateway is None:
        stytch_gateway = StytchB2BSessionGateway(
            project_id=application_settings.stytch_project_id,
            secret=application_settings.stytch_secret.get_secret_value(),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        session_bind = session_factory.kw.get("bind")
        if session_bind is not None:
            validate_runtime_database_security(session_bind)
        yield
        if managed_engine is not None:
            managed_engine.dispose()

    app = FastAPI(title="Privexa API", version="0.2.0", lifespan=lifespan)
    app.state.settings = application_settings
    app.state.session_factory = session_factory
    app.state.stytch_gateway = stytch_gateway

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[application_settings.privexa_web_origin.rstrip("/")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    app.add_middleware(
        CookieCsrfMiddleware,
        trusted_origin=application_settings.privexa_web_origin,
        session_cookie_name="stytch_session",
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_exception_handler(AuthenticationProblem, authentication_problem_handler)
    app.add_exception_handler(AuthorizationProblem, authorization_problem_handler)
    app.add_exception_handler(DatabaseSecurityError, database_security_problem_handler)
    app.add_exception_handler(DBAPIError, database_operation_problem_handler)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(authentication_router, prefix="/v1")
    return app
