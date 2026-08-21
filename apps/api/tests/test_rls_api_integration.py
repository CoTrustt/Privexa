from __future__ import annotations

import io
import logging
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ALICE_APOLLO_GRANT_ID,
    APOLLO_FINANCE_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientAuthorizationContext
from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.errors import AuthorizationResourceNotFoundError
from privexa_api.access_control.models import ClientAccessGrant
from privexa_api.access_control.permissions import Permission
from privexa_api.api.authorization_dependencies import require_client_permission
from privexa_api.api.dependencies import get_database_session
from privexa_api.api.errors import DATABASE_SECURITY_LOGGER
from privexa_api.clients.models import ClientWorkspace
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app

ClientReadAuthorization = Annotated[
    ClientAuthorizationContext,
    Depends(require_client_permission(Permission.CLIENT_READ)),
]
DatabaseSession = Annotated[Session, Depends(get_database_session)]
pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _build_security_client(app_engine: Engine) -> TestClient:
    settings = Settings(
        APP_DATABASE_URL="postgresql+psycopg://unused",
        STYTCH_PROJECT_ID="project-test-privexa",
        STYTCH_SECRET=SecretStr("secret-test-privexa"),
        PRIVEXA_ENVIRONMENT="test",
        PRIVEXA_WEB_ORIGIN="http://localhost:3000",
    )
    app = create_app(
        settings=settings,
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )

    @app.get("/security/clients/{client_id}/unfiltered")
    def unfiltered_client_query(
        authorization: ClientReadAuthorization,
        session: DatabaseSession,
    ) -> dict[str, list[str]]:
        del authorization
        return {
            "client_ids": [str(value) for value in session.scalars(select(ClientWorkspace.id))],
            "grant_ids": [str(value) for value in session.scalars(select(ClientAccessGrant.id))],
        }

    @app.get("/security/clients/{client_id}/objects/{object_id}")
    def direct_object_lookup(
        object_id: UUID,
        authorization: ClientReadAuthorization,
        session: DatabaseSession,
    ) -> dict[str, str]:
        del authorization
        client = session.get(ClientWorkspace, object_id)
        if client is None:
            raise AuthorizationResourceNotFoundError(
                reason=AuthorizationFailureReason.CLIENT_ACCESS_REQUIRED,
                permission=Permission.CLIENT_READ,
            )
        return {"client_id": str(client.id), "name": client.name}

    @app.post("/security/clients/{client_id}/unsafe-cross-firm-write")
    def unsafe_cross_firm_write(
        authorization: ClientReadAuthorization,
        session: DatabaseSession,
    ) -> dict[str, str]:
        del authorization
        malicious_id = uuid4()
        session.add(
            ClientWorkspace(
                id=malicious_id,
                firm_id=FIRM_B_ID,
                name="Must Never Be Written",
            )
        )
        session.flush()
        return {"client_id": str(malicious_id)}

    @app.get("/security/missing-context-write")
    def missing_context_write(session: DatabaseSession) -> dict[str, str]:
        malicious_id = uuid4()
        session.add(
            ClientWorkspace(
                id=malicious_id,
                firm_id=FIRM_B_ID,
                name="Must Never Be Written",
            )
        )
        session.flush()
        return {"client_id": str(malicious_id)}

    return TestClient(app, raise_server_exceptions=False)


def test_authenticated_authorized_request_establishes_context_before_unfiltered_query(
    tenant_data,
    app_engine: Engine,
) -> None:
    with _build_security_client(app_engine) as client:
        client.cookies.set("stytch_session", "alice-token")
        response = client.get(f"/security/clients/{APOLLO_FINANCE_ID}/unfiltered")

    assert response.status_code == 200
    assert response.json() == {
        "client_ids": [str(APOLLO_FINANCE_ID)],
        "grant_ids": [str(ALICE_APOLLO_GRANT_ID)],
    }


def test_manipulated_client_identifier_is_rejected_before_business_access(
    tenant_data,
    app_engine: Engine,
) -> None:
    with _build_security_client(app_engine) as client:
        client.cookies.set("stytch_session", "alice-token")
        beta = client.get(
            f"/security/clients/{MERIDIAN_RETAIL_ID}/unfiltered",
            headers={
                "X-Firm-ID": str(FIRM_B_ID),
                "X-Client-ID": str(APOLLO_FINANCE_ID),
                "X-Role": "FIRM_OWNER",
            },
        )
        gamma = client.get(f"/security/clients/{NORTHSTAR_RETAIL_ID}/unfiltered")

    for response in (beta, gamma):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert response.json()["detail"] == "The requested resource could not be found."


def test_manipulated_object_identifier_is_invisible_inside_valid_alpha_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    with _build_security_client(app_engine) as client:
        client.cookies.set("stytch_session", "alice-token")
        allowed = client.get(f"/security/clients/{APOLLO_FINANCE_ID}/objects/{APOLLO_FINANCE_ID}")
        beta = client.get(f"/security/clients/{APOLLO_FINANCE_ID}/objects/{MERIDIAN_RETAIL_ID}")
        gamma = client.get(f"/security/clients/{APOLLO_FINANCE_ID}/objects/{NORTHSTAR_RETAIL_ID}")

    assert allowed.status_code == 200
    assert allowed.json()["client_id"] == str(APOLLO_FINANCE_ID)
    for response in (beta, gamma):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert "Meridian" not in response.text
        assert "Northstar" not in response.text


def test_rls_write_failure_is_customer_safe_and_next_tenant_request_still_works(
    tenant_data,
    app_engine: Engine,
) -> None:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    DATABASE_SECURITY_LOGGER.addHandler(handler)
    try:
        with _build_security_client(app_engine) as client:
            client.cookies.set("stytch_session", "alice-token")
            denied = client.post(
                f"/security/clients/{APOLLO_FINANCE_ID}/unsafe-cross-firm-write",
                headers={"Origin": "http://localhost:3000"},
            )
            client.cookies.set("stytch_session", "bob-token")
            subsequent = client.get(f"/security/clients/{NORTHSTAR_RETAIL_ID}/unfiltered")
    finally:
        DATABASE_SECURITY_LOGGER.removeHandler(handler)

    assert denied.status_code == 403
    assert denied.json()["code"] == "FORBIDDEN"
    assert denied.json()["detail"] == "You do not have permission to perform this action."
    prohibited_fragments = (
        "row-level security",
        "client_workspaces",
        "privexa.client_id",
        "INSERT INTO",
        "alice-token",
        "Must Never Be Written",
    )
    assert all(fragment not in denied.text for fragment in prohibited_fragments)
    assert all(fragment not in output.getvalue() for fragment in prohibited_fragments)
    assert subsequent.status_code == 200
    assert subsequent.json()["client_ids"] == [str(NORTHSTAR_RETAIL_ID)]


def test_missing_database_context_failure_is_customer_safe(
    tenant_data,
    app_engine: Engine,
) -> None:
    with _build_security_client(app_engine) as client:
        response = client.get("/security/missing-context-write")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["detail"] == "You do not have permission to perform this action."
    assert all(
        fragment not in response.text
        for fragment in (
            "row-level security",
            "client_workspaces",
            "privexa.firm_id",
            "postgresql",
            "traceback",
        )
    )
