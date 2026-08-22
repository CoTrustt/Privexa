from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.ai_gateway.factory import build_ai_gateway
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.telemetry import configure_ai_gateway_logging
from privexa_api.ai_policy.telemetry import configure_ai_policy_logging
from privexa_api.api.authorization_dependencies import configure_authorization_logging
from privexa_api.api.dependencies import configure_authentication_logging
from privexa_api.api.errors import (
    application_context_problem_handler,
    authentication_problem_handler,
    authorization_problem_handler,
    database_operation_problem_handler,
    database_security_problem_handler,
    file_problem_handler,
)
from privexa_api.api.middleware import CookieCsrfMiddleware, RequestContextMiddleware
from privexa_api.api.routes.ai_tasks import router as ai_tasks_router
from privexa_api.api.routes.application_context import router as application_context_router
from privexa_api.api.routes.authentication import router as authentication_router
from privexa_api.api.routes.files import router as files_router
from privexa_api.application_context.errors import ApplicationContextProblem
from privexa_api.application_context.service import configure_application_context_logging
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
from privexa_api.files.errors import FileProblem
from privexa_api.files.service import StoredFileService, configure_file_logging
from privexa_api.observability.tracing import configure_tracing
from privexa_api.security.execution_context import configure_sensitivity_logging
from privexa_api.storage.gateway import ObjectStorageGateway
from privexa_api.storage.s3 import S3ObjectStorageGateway


def create_app(
    *,
    settings: Settings | None = None,
    stytch_gateway: StytchSessionGateway | None = None,
    object_storage_gateway: ObjectStorageGateway | None = None,
    ai_gateway: AIGateway | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    configure_authentication_logging()
    configure_authorization_logging()
    configure_sensitivity_logging()
    configure_file_logging()
    configure_application_context_logging()
    configure_ai_gateway_logging()
    configure_ai_policy_logging()
    configure_tracing()
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
    if object_storage_gateway is None:
        object_storage_gateway = S3ObjectStorageGateway(
            bucket=application_settings.object_storage_bucket,
            region=application_settings.object_storage_region,
            endpoint_url=application_settings.object_storage_endpoint_url,
            access_key=(
                application_settings.object_storage_access_key.get_secret_value()
                if application_settings.object_storage_access_key is not None
                else None
            ),
            secret_key=(
                application_settings.object_storage_secret_key.get_secret_value()
                if application_settings.object_storage_secret_key is not None
                else None
            ),
            addressing_style=application_settings.object_storage_addressing_style,
        )
    managed_ai_gateway = ai_gateway is None
    if ai_gateway is None:
        ai_gateway = build_ai_gateway(application_settings, session_factory=session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            session_bind = session_factory.kw.get("bind")
            if session_bind is not None:
                validate_runtime_database_security(session_bind)
            with session_factory() as policy_session, policy_session.begin():
                ai_gateway.validate_policy_startup(policy_session)
            yield
        finally:
            if managed_ai_gateway:
                await ai_gateway.aclose()
            if managed_engine is not None:
                managed_engine.dispose()

    app = FastAPI(title="Privexa API", version="0.2.0", lifespan=lifespan)
    app.state.settings = application_settings
    app.state.session_factory = session_factory
    app.state.stytch_gateway = stytch_gateway
    app.state.ai_gateway = ai_gateway
    app.state.stored_file_service = StoredFileService(
        storage=object_storage_gateway,
        bucket=application_settings.object_storage_bucket,
        upload_ttl_seconds=application_settings.file_upload_url_ttl_seconds,
        upload_completion_grace_seconds=(application_settings.file_upload_completion_grace_seconds),
        download_ttl_seconds=application_settings.file_download_url_ttl_seconds,
        max_upload_size_bytes=application_settings.max_file_upload_size_bytes,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[application_settings.privexa_web_origin.rstrip("/")],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
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
    app.add_exception_handler(FileProblem, file_problem_handler)
    app.add_exception_handler(ApplicationContextProblem, application_context_problem_handler)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(authentication_router, prefix="/v1")
    app.include_router(application_context_router, prefix="/v1")
    app.include_router(files_router, prefix="/v1")
    app.include_router(ai_tasks_router, prefix="/v1")
    return app
