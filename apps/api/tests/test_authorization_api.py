from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ALICE_APOLLO_GRANT_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    ANITA_ID,
    APOLLO_FINANCE_ID,
    DAVID_MEMBERSHIP_ID,
    FIRM_A_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine, delete, update
from sqlalchemy.orm import Session

from privexa_api.access_control.context import (
    ClientAuthorizationContext,
    FirmAuthorizationContext,
)
from privexa_api.access_control.enums import ClientAccessStatus, FirmRole, MembershipStatus
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.access_control.permissions import Permission
from privexa_api.api.authorization_dependencies import (
    LOGGER,
    require_client_permission,
    require_firm_permission,
)
from privexa_api.api.dependencies import get_database_session
from privexa_api.clients.service import ClientWorkspaceService
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app

FirmReadAuthorization = Annotated[
    FirmAuthorizationContext,
    Depends(require_firm_permission(Permission.FIRM_READ)),
]
FirmMemberManagementAuthorization = Annotated[
    FirmAuthorizationContext,
    Depends(require_firm_permission(Permission.FIRM_MEMBERS_MANAGE)),
]
ClientReadAuthorization = Annotated[
    ClientAuthorizationContext,
    Depends(require_client_permission(Permission.CLIENT_READ)),
]
DatabaseSession = Annotated[Session, Depends(get_database_session)]
pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _build_client(
    app_engine: Engine,
    *,
    gateway: MultiIdentityStytchGateway | None = None,
) -> TestClient:
    settings = Settings(
        APP_DATABASE_URL="postgresql+psycopg://unused",
        STYTCH_PROJECT_ID="project-test-privexa",
        STYTCH_SECRET=SecretStr("secret-test-privexa"),
        PRIVEXA_ENVIRONMENT="test",
        PRIVEXA_WEB_ORIGIN="http://localhost:3000",
    )
    app = create_app(
        settings=settings,
        stytch_gateway=gateway or MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )

    @app.get("/test/firm")
    def read_firm(authorization: FirmReadAuthorization) -> dict[str, str]:
        return {"firm_id": str(authorization.firm_context.firm_id)}

    @app.post("/test/firm/members")
    def manage_members(
        authorization: FirmMemberManagementAuthorization,
    ) -> dict[str, str]:
        return {"firm_id": str(authorization.firm_context.firm_id)}

    @app.get("/test/clients/{client_id}")
    def read_client(
        authorization: ClientReadAuthorization,
        session: DatabaseSession,
    ) -> dict[str, str]:
        client = ClientWorkspaceService.get_current(
            session,
            authorization=authorization,
        )
        return {"client_id": str(client.id), "name": client.name}

    return TestClient(app)


def test_client_authorization_preserves_authentication_boundary(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)

    response = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_assigned_client_is_available_through_authorized_service(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    response = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "client_id": str(APOLLO_FINANCE_ID),
        "name": "Apollo Finance",
    }


def test_unassigned_and_cross_firm_clients_have_same_not_found_contract(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    unassigned = client.get(f"/test/clients/{MERIDIAN_RETAIL_ID}")
    cross_firm = client.get(f"/test/clients/{NORTHSTAR_RETAIL_ID}")

    for response in (unassigned, cross_firm):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert response.json()["detail"] == "The requested resource could not be found."


def test_valid_consultant_receives_forbidden_for_admin_operation(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    readable = client.get("/test/firm")
    forbidden = client.post(
        "/test/firm/members",
        headers={"Origin": "http://localhost:3000"},
    )

    assert readable.status_code == 200
    assert readable.json()["firm_id"] == str(FIRM_A_ID)
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "FORBIDDEN"


def test_authorization_logs_private_reason_without_tokens_or_client_names(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    LOGGER.addHandler(handler)

    try:
        response = client.get(f"/test/clients/{MERIDIAN_RETAIL_ID}")
    finally:
        LOGGER.removeHandler(handler)

    logged = output.getvalue()
    assert response.status_code == 404
    assert "AUTHZ_CLIENT_ACCESS_REQUIRED" in logged
    assert str(ALICE_ID) in logged
    assert "alice-token" not in logged
    assert "Meridian Retail" not in logged


def test_authorization_denial_log_is_structured_and_contains_required_safe_fields(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "anita-token")
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    LOGGER.addHandler(handler)

    try:
        response = client.get(f"/test/clients/{MERIDIAN_RETAIL_ID}")
    finally:
        LOGGER.removeHandler(handler)

    event = json.loads(output.getvalue())
    assert response.status_code == 404
    assert event == {
        "client_id": str(MERIDIAN_RETAIL_ID),
        "decision": "DENY",
        "event": "authorization.denied",
        "firm_id": str(FIRM_A_ID),
        "membership_id": str(tenant_data.anita_membership.id),
        "permission": "client.read",
        "principal_id": str(ANITA_ID),
        "reason_code": "AUTHZ_CLIENT_ACCESS_REQUIRED",
        "request_id": response.json()["request_id"],
    }


def test_invalid_and_expired_sessions_return_401_for_protected_route(
    tenant_data,
    app_engine: Engine,
) -> None:
    for token in ("invalid-token", "expired-token"):
        client = _build_client(app_engine)
        client.cookies.set("stytch_session", token)
        response = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Session"


def test_revoked_provider_session_is_denied_before_authorization(
    tenant_data,
    app_engine: Engine,
) -> None:
    gateway = MultiIdentityStytchGateway()
    client = _build_client(app_engine, gateway=gateway)
    client.cookies.set("stytch_session", "alice-token")
    assert client.get(f"/test/clients/{APOLLO_FINANCE_ID}").status_code == 200

    gateway.revoke("alice-token")
    denied = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert denied.status_code == 401
    assert denied.json()["code"] == "SESSION_EXPIRED"
    assert denied.headers["www-authenticate"] == "Session"


def test_jwt_cookie_without_supported_opaque_session_cannot_authenticate(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session_jwt", "untrusted-jwt-claims")

    denied = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert denied.status_code == 401
    assert denied.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_valid_provider_session_without_local_membership_returns_403(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "unprovisioned-token")

    response = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert response.status_code == 403
    assert response.json()["code"] == "MEMBER_NOT_PROVISIONED"


def test_assignment_revocation_denies_same_authenticated_session(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert client.get(f"/test/clients/{APOLLO_FINANCE_ID}").status_code == 200

    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientAccessGrant)
            .where(ClientAccessGrant.id == ALICE_APOLLO_GRANT_ID)
            .values(status=ClientAccessStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    denied = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")
    assert denied.status_code == 404
    assert denied.json()["code"] == "RESOURCE_NOT_FOUND"


def test_deleted_membership_denies_same_unexpired_provider_session(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert client.get(f"/test/clients/{APOLLO_FINANCE_ID}").status_code == 200

    with Session(owner_engine) as session, session.begin():
        session.execute(
            delete(ClientAccessGrant).where(
                ClientAccessGrant.membership_id == ALICE_MEMBERSHIP_ID
            )
        )
        session.execute(
            delete(FirmMembership).where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
        )

    denied = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert denied.status_code == 403
    assert denied.json()["code"] == "MEMBER_NOT_PROVISIONED"


def test_membership_reactivation_uses_current_state_with_same_session(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert client.get(f"/test/clients/{APOLLO_FINANCE_ID}").status_code == 200

    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
            .values(status=MembershipStatus.SUSPENDED)
        )
    suspended = client.get(f"/test/clients/{APOLLO_FINANCE_ID}")
    assert suspended.status_code == 403
    assert suspended.json()["code"] == "MEMBERSHIP_INACTIVE"

    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
            .values(status=MembershipStatus.ACTIVE)
        )
    assert client.get(f"/test/clients/{APOLLO_FINANCE_ID}").status_code == 200


def test_role_downgrade_and_promotion_take_effect_without_new_session(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    admin_client = _build_client(app_engine)
    admin_client.cookies.set("stytch_session", "david-token")
    assert (
        admin_client.post(
            "/test/firm/members",
            headers={"Origin": "http://localhost:3000"},
        ).status_code
        == 200
    )
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == DAVID_MEMBERSHIP_ID)
            .values(role=FirmRole.CONSULTANT)
        )
    assert (
        admin_client.post(
            "/test/firm/members",
            headers={"Origin": "http://localhost:3000"},
        ).status_code
        == 403
    )

    consultant_client = _build_client(app_engine)
    consultant_client.cookies.set("stytch_session", "alice-token")
    assert (
        consultant_client.post(
            "/test/firm/members",
            headers={"Origin": "http://localhost:3000"},
        ).status_code
        == 403
    )
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
            .values(role=FirmRole.FIRM_ADMIN)
        )
    assert (
        consultant_client.post(
            "/test/firm/members",
            headers={"Origin": "http://localhost:3000"},
        ).status_code
        == 200
    )


def test_privilege_headers_and_query_scope_cannot_elevate_consultant(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "anita-token")
    headers = {
        "X-User-ID": str(tenant_data.david.id),
        "X-Firm-ID": str(FIRM_A_ID),
        "X-Role": "FIRM_OWNER",
        "X-Client-ID": str(MERIDIAN_RETAIL_ID),
    }

    denied = client.get(f"/test/clients/{MERIDIAN_RETAIL_ID}", headers=headers)
    allowed_path_wins = client.get(
        f"/test/clients/{APOLLO_FINANCE_ID}",
        params={"client_id": MERIDIAN_RETAIL_ID, "firm_id": tenant_data.firm_b.id},
        headers=headers,
    )

    assert denied.status_code == 404
    assert allowed_path_wins.status_code == 200
    assert allowed_path_wins.json()["client_id"] == str(APOLLO_FINANCE_ID)


def test_body_overposting_cannot_grant_administrator_permission(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "anita-token")

    response = client.post(
        "/test/firm/members",
        json={
            "role": "FIRM_OWNER",
            "permissions": ["firm.members.manage"],
            "is_admin": True,
            "firm_id": str(FIRM_A_ID),
        },
        headers={"Origin": "http://localhost:3000"},
    )

    assert response.status_code == 403


def test_malformed_and_nonexistent_identifiers_do_not_bypass_authorization(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "anita-token")

    malformed = client.get("/test/clients/not-a-uuid")
    nonexistent = client.get(f"/test/clients/{uuid4()}")
    foreign = client.get(f"/test/clients/{NORTHSTAR_RETAIL_ID}")

    assert malformed.status_code == 422
    for response in (nonexistent, foreign):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert response.json()["detail"] == "The requested resource could not be found."


def test_request_local_authorization_context_does_not_leak_between_firms(
    tenant_data,
    app_engine: Engine,
) -> None:
    firm_a_client = _build_client(app_engine)
    firm_a_client.cookies.set("stytch_session", "alice-token")
    firm_b_client = _build_client(app_engine)
    firm_b_client.cookies.set("stytch_session", "bob-token")

    first = firm_a_client.get(f"/test/clients/{APOLLO_FINANCE_ID}")
    second = firm_b_client.get(f"/test/clients/{NORTHSTAR_RETAIL_ID}")
    first_cross = firm_a_client.get(f"/test/clients/{NORTHSTAR_RETAIL_ID}")
    second_cross = firm_b_client.get(f"/test/clients/{APOLLO_FINANCE_ID}")

    assert first.status_code == second.status_code == 200
    assert first_cross.status_code == second_cross.status_code == 404


def test_public_health_and_openapi_generation_remain_available(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)

    health = client.get("/health")
    openapi = client.get("/openapi.json")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert openapi.status_code == 200
    assert "/test/clients/{client_id}" in openapi.json()["paths"]
