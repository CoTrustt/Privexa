from __future__ import annotations

from fastapi.routing import APIRoute
from fixtures.tenant_foundation import STYTCH_ALICE_ID, STYTCH_FIRM_A_ID
from pydantic import SecretStr
from sqlalchemy import Engine

from privexa_api.api.dependencies import require_authenticated_identity
from privexa_api.authentication.stytch_gateway import ValidatedStytchSession
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app


class FakeStytchGateway:
    def authenticate(self, session_token: str) -> ValidatedStytchSession:
        return ValidatedStytchSession(
            member_id=STYTCH_ALICE_ID,
            organization_id=STYTCH_FIRM_A_ID,
            member_session_id="member-session-test-alice",
            request_id="request-test-alice",
        )

    def revoke(self, session_token: str) -> None:
        return None


def _flatten_routes(app) -> list[tuple[str, object]]:
    flattened: list[tuple[str, object]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            flattened.append((path, route))
            continue
        original_router = getattr(route, "original_router", None)
        include_context = getattr(route, "include_context", None)
        if original_router is None or include_context is None:
            continue
        for included_route in original_router.routes:
            included_path = getattr(included_route, "path", None)
            if isinstance(included_path, str):
                flattened.append((f"{include_context.prefix}{included_path}", included_route))
    return flattened


def test_every_production_route_has_an_explicit_protection_classification(
    tenant_data,
    app_engine: Engine,
) -> None:
    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="test",
            PRIVEXA_WEB_ORIGIN="http://localhost:3000",
        ),
        stytch_gateway=FakeStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )
    public_paths = {
        "/docs",
        "/docs/oauth2-redirect",
        "/health",
        "/openapi.json",
        "/redoc",
        "/v1/auth/logout",
    }
    authenticated_paths = {"/v1/auth/session"}

    flattened_routes = _flatten_routes(app)
    assert {path for path, _ in flattened_routes} == public_paths | authenticated_paths

    session_route = next(
        route
        for path, route in flattened_routes
        if isinstance(route, APIRoute) and path == "/v1/auth/session"
    )
    dependency_calls = {
        dependency.call
        for dependency in session_route.dependant.dependencies
        if dependency.call is not None
    }
    assert require_authenticated_identity in dependency_calls
