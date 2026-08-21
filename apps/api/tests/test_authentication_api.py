from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from fastapi.testclient import TestClient
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    STYTCH_ALICE_ID,
    STYTCH_FIRM_A_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from privexa_api.api.dependencies import LOGGER, get_database_session
from privexa_api.authentication.errors import (
    AuthenticationFailedError,
    AuthenticationServiceUnavailableError,
    SessionExpiredError,
)
from privexa_api.authentication.stytch_gateway import ValidatedStytchSession
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app


@dataclass
class FakeStytchGateway:
    revoked_tokens: list[str] = field(default_factory=list)

    def authenticate(self, session_token: str) -> ValidatedStytchSession:
        if session_token == "expired":
            raise SessionExpiredError
        if session_token == "invalid":
            raise AuthenticationFailedError
        if session_token == "unavailable":
            raise AuthenticationServiceUnavailableError
        if session_token == "unknown":
            member_id = "member-test-unknown"
            organization_id = STYTCH_FIRM_A_ID
        else:
            member_id = STYTCH_ALICE_ID
            organization_id = STYTCH_FIRM_A_ID
        return ValidatedStytchSession(
            member_id=member_id,
            organization_id=organization_id,
            member_session_id=f"member-session-{session_token}",
            request_id=f"request-{session_token}",
        )

    def revoke(self, session_token: str) -> None:
        self.revoked_tokens.append(session_token)


def _build_client(
    app_engine: Engine,
    *,
    environment: str = "test",
) -> tuple[TestClient, FakeStytchGateway]:
    gateway = FakeStytchGateway()
    settings = Settings(
        APP_DATABASE_URL="postgresql+psycopg://unused",
        STYTCH_PROJECT_ID="project-test-privexa",
        STYTCH_SECRET=SecretStr("secret-test-privexa"),
        PRIVEXA_ENVIRONMENT=environment,
        PRIVEXA_WEB_ORIGIN="http://localhost:3000",
    )
    app = create_app(
        settings=settings,
        stytch_gateway=gateway,
        session_factory=build_session_factory(app_engine),
    )
    return TestClient(app), gateway


def test_protected_session_requires_authentication(tenant_data, app_engine: Engine) -> None:
    client, _ = _build_client(app_engine)

    response = client.get("/v1/auth/session")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"
    assert response.headers["cache-control"] == "no-store"


def test_protected_session_returns_privexa_identity(tenant_data, app_engine: Engine) -> None:
    client, _ = _build_client(app_engine)
    client.cookies.set("stytch_session", "valid")

    response = client.get(
        "/v1/auth/session",
        params={"firm_id": str(FIRM_B_ID)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(ALICE_ID),
        "membership_id": str(ALICE_MEMBERSHIP_ID),
        "firm_id": str(FIRM_A_ID),
        "role": "CONSULTANT",
        "display_name": "Consultant Alice",
        "firm_name": "Pai Privacy Consulting",
    }
    assert response.headers["cache-control"] == "private, no-store"


def test_unknown_identity_is_not_auto_provisioned(tenant_data, app_engine: Engine) -> None:
    client, _ = _build_client(app_engine)
    client.cookies.set("stytch_session", "unknown")

    response = client.get("/v1/auth/session")

    assert response.status_code == 403
    assert response.json()["code"] == "MEMBER_NOT_PROVISIONED"


def test_provider_session_failures_have_stable_error_codes(tenant_data, app_engine: Engine) -> None:
    client, _ = _build_client(app_engine)

    expected = {
        "invalid": (401, "AUTHENTICATION_FAILED"),
        "expired": (401, "SESSION_EXPIRED"),
        "unavailable": (503, "AUTHENTICATION_SERVICE_UNAVAILABLE"),
    }
    for token, (status_code, code) in expected.items():
        client.cookies.set("stytch_session", token)
        response = client.get("/v1/auth/session")
        assert response.status_code == status_code
        assert response.json()["code"] == code


def test_logout_requires_same_origin_and_revokes_session(tenant_data, app_engine: Engine) -> None:
    client, gateway = _build_client(app_engine)
    client.cookies.set("stytch_session", "valid")

    rejected = client.post("/v1/auth/logout", headers={"Origin": "https://attacker.example"})
    accepted = client.post("/v1/auth/logout", headers={"Origin": "http://localhost:3000"})

    assert rejected.status_code == 403
    assert rejected.json()["code"] == "CSRF_VALIDATION_FAILED"
    assert accepted.status_code == 204
    assert gateway.revoked_tokens == ["valid"]
    assert "stytch_session=" in accepted.headers.get("set-cookie", "")


def test_production_logout_cookie_expiry_is_secure_and_http_only(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, _ = _build_client(app_engine, environment="production")
    client.cookies.set("stytch_session", "valid")

    response = client.post("/v1/auth/logout", headers={"Origin": "http://localhost:3000"})

    set_cookie = response.headers.get("set-cookie", "")
    assert response.status_code == 204
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie


def test_cors_allows_only_the_configured_credentialed_origin(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, _ = _build_client(app_engine)
    preflight_headers = {"Access-Control-Request-Method": "POST"}

    trusted = client.options(
        "/v1/auth/logout",
        headers={"Origin": "http://localhost:3000", **preflight_headers},
    )
    untrusted = client.options(
        "/v1/auth/logout",
        headers={"Origin": "https://attacker.example", **preflight_headers},
    )

    assert trusted.status_code == 200
    assert trusted.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert trusted.headers["access-control-allow-credentials"] == "true"
    assert untrusted.status_code == 400
    assert "access-control-allow-origin" not in untrusted.headers


def test_database_dependency_uses_the_injected_runtime_factory(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, _ = _build_client(app_engine)
    assert get_database_session is not None
    assert isinstance(client.app.state.session_factory, sessionmaker)


def test_authentication_logs_events_without_session_secrets(
    tenant_data,
    app_engine: Engine,
) -> None:
    client, _ = _build_client(app_engine)
    log_output = io.StringIO()
    capture_handler = logging.StreamHandler(log_output)
    LOGGER.addHandler(capture_handler)

    try:
        client.cookies.set("stytch_session", "sensitive-opaque-token")
        assert client.get("/v1/auth/session").status_code == 200
        assert (
            client.post("/v1/auth/logout", headers={"Origin": "http://localhost:3000"}).status_code
            == 204
        )
    finally:
        LOGGER.removeHandler(capture_handler)

    logged = log_output.getvalue()
    assert "authentication.principal_resolved" in logged
    assert "authentication.logout_completed" in logged
    assert "sensitive-opaque-token" not in logged
    assert STYTCH_ALICE_ID not in logged
    assert STYTCH_FIRM_A_ID not in logged
