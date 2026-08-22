from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from fixtures.authorization import TEST_IDENTITIES, MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_ACME_GRANT_ID,
    ALICE_APOLLO_GRANT_ID,
    ALICE_RESTRICTED_GRANT_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
    RESTRICTED_CLIENT_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import ClientAccessStatus, MembershipStatus
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.access_control.permissions import Permission
from privexa_api.api.authorization_dependencies import require_active_client_permission
from privexa_api.application_context.models import ActiveClientSession
from privexa_api.application_context.service import LOGGER, session_fingerprint
from privexa_api.authentication.errors import AuthenticationFailedError, SessionExpiredError
from privexa_api.authentication.stytch_gateway import ValidatedStytchSession
from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.clients.models import ClientWorkspace
from privexa_api.config import Settings
from privexa_api.db.session import build_session_factory
from privexa_api.main import create_app
from privexa_api.security.execution_context import ExecutionContext

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

ActiveClientContext = Annotated[
    ExecutionContext,
    Depends(require_active_client_permission(Permission.CLIENT_READ)),
]


class SessionSpecificGateway:
    def authenticate(self, session_token: str) -> ValidatedStytchSession:
        if session_token == "expired-token":
            raise SessionExpiredError
        identity = TEST_IDENTITIES.get("alice-token")
        if session_token not in {"alice-tab-a", "alice-tab-b"} or identity is None:
            raise AuthenticationFailedError
        return ValidatedStytchSession(
            member_id=identity.member_id,
            organization_id=identity.organization_id,
            member_session_id=f"session-{session_token}",
            request_id=f"request-{session_token}",
        )

    def revoke(self, session_token: str) -> None:
        return None


def _build_client(
    app_engine: Engine,
    *,
    gateway: MultiIdentityStytchGateway | SessionSpecificGateway | None = None,
) -> TestClient:
    app = create_app(
        settings=Settings(
            APP_DATABASE_URL="postgresql+psycopg://unused",
            STYTCH_PROJECT_ID="project-test-privexa",
            STYTCH_SECRET=SecretStr("secret-test-privexa"),
            PRIVEXA_ENVIRONMENT="test",
            PRIVEXA_WEB_ORIGIN="http://localhost:3000",
        ),
        stytch_gateway=gateway or MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )

    @app.get("/test/active-client-context")
    def active_client_context(context: ActiveClientContext) -> dict[str, str]:
        assert context.client_id is not None
        return {"client_id": str(context.client_id)}

    @app.get("/test/active-client-security-context")
    def active_client_security_context(context: ActiveClientContext) -> dict[str, object]:
        assert context.client_id is not None
        return {
            "request_id": str(context.request_id),
            "user_id": str(context.user_id),
            "membership_id": str(context.membership_id),
            "firm_id": str(context.firm_id),
            "client_id": str(context.client_id),
            "firm_role": context.firm_role.value,
            "authorization_scope": context.authorization_scope.value,
            "granted_capabilities": sorted(
                capability.value for capability in context.granted_capabilities
            ),
            "effective_sensitivity": context.effective_sensitivity.value,
            "originating_channel": context.originating_channel.value,
            "trace_id": context.trace_id,
        }

    return TestClient(app)


def _activate(client: TestClient, client_id) -> object:
    return client.put(
        f"/v1/application-context/active-client/{client_id}",
        headers={"Origin": "http://localhost:3000"},
    )


def test_application_context_requires_a_valid_provider_session(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    assert client.get("/v1/application-context").status_code == 401

    client.cookies.set("stytch_session", "expired-token")
    expired = client.get("/v1/application-context")
    assert expired.status_code == 401
    assert expired.json()["code"] == "SESSION_EXPIRED"


def test_client_switch_requires_authentication_and_the_trusted_cookie_origin(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    missing_session = _activate(client, APOLLO_FINANCE_ID)
    assert missing_session.status_code == 401
    assert missing_session.json()["code"] == "AUTHENTICATION_REQUIRED"

    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200
    cross_origin = client.put(
        f"/v1/application-context/active-client/{ACME_HEALTHCARE_ID}",
        headers={"Origin": "https://attacker.example"},
    )

    assert cross_origin.status_code == 403
    assert cross_origin.json()["code"] == "CSRF_VALIDATION_FAILED"
    assert client.get("/test/active-client-context").json() == {"client_id": str(APOLLO_FINANCE_ID)}


def test_context_lists_only_authorized_clients_and_requires_explicit_selection(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    response = client.get("/v1/application-context")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "state": "CLIENT_SELECTION_REQUIRED",
        "user": {"id": str(tenant_data.alice.id), "display_name": "Consultant Alice"},
        "firm": {"id": str(FIRM_A_ID), "display_name": "Pai Privacy Consulting"},
        "active_client": None,
        "question_capabilities": {"can_create": False, "can_update": False},
        "authorised_clients": [
            {"id": str(ACME_HEALTHCARE_ID), "display_name": "Acme Healthcare"},
            {"id": str(APOLLO_FINANCE_ID), "display_name": "Apollo Finance"},
            {"id": str(RESTRICTED_CLIENT_ID), "display_name": "Restricted Client Demo"},
        ],
    }
    serialized = response.text
    assert "Meridian Retail" not in serialized
    assert "Northstar Retail" not in serialized
    assert "session-" not in serialized
    assert set(response.json()) == {
        "state",
        "user",
        "firm",
        "active_client",
        "authorised_clients",
        "question_capabilities",
    }
    assert set(response.json()["user"]) == {"id", "display_name"}
    assert set(response.json()["firm"]) == {"id", "display_name"}
    assert all(
        set(projected_client) == {"id", "display_name"}
        for projected_client in response.json()["authorised_clients"]
    )
    for forbidden_value in (
        "stytch_session",
        "granted_capabilities",
        "effective_sensitivity",
        "authorization_scope",
        "membership_id",
    ):
        assert forbidden_value not in serialized


def test_authorized_switch_changes_subsequent_canonical_execution_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    first = _activate(client, APOLLO_FINANCE_ID)
    apollo_context = client.get("/test/active-client-context")
    second = _activate(client, ACME_HEALTHCARE_ID)
    acme_context = client.get("/test/active-client-context")

    assert first.status_code == 200
    assert first.json()["active_client"]["id"] == str(APOLLO_FINANCE_ID)
    assert apollo_context.json() == {"client_id": str(APOLLO_FINANCE_ID)}
    assert second.status_code == 200
    assert second.json()["active_client"]["id"] == str(ACME_HEALTHCARE_ID)
    assert acme_context.json() == {"client_id": str(ACME_HEALTHCARE_ID)}
    resolved = client.get("/v1/application-context").json()
    assert resolved["state"] == "ACTIVE_CLIENT"
    assert resolved["active_client"]["id"] == str(ACME_HEALTHCARE_ID)
    assert resolved["question_capabilities"] == {"can_create": True, "can_update": True}


def test_question_capability_projection_is_read_only_guidance(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "mark-token")
    assert _activate(client, ACME_HEALTHCARE_ID).status_code == 200

    response = client.get("/v1/application-context")

    assert response.status_code == 200
    assert response.json()["question_capabilities"] == {
        "can_create": False,
        "can_update": False,
    }


def test_switch_preserves_canonical_security_context_fields_and_request_immutability(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    before = client.get("/test/active-client-security-context")
    switched = _activate(client, ACME_HEALTHCARE_ID)
    after = client.get("/test/active-client-security-context")

    assert switched.status_code == 200
    assert before.json()["client_id"] == str(APOLLO_FINANCE_ID)
    assert after.json()["client_id"] == str(ACME_HEALTHCARE_ID)
    stable_fields = {
        "user_id": str(tenant_data.alice.id),
        "membership_id": str(tenant_data.alice_membership.id),
        "firm_id": str(FIRM_A_ID),
        "firm_role": "CONSULTANT",
        "authorization_scope": "CLIENT",
        "granted_capabilities": ["client.read"],
        "effective_sensitivity": "STANDARD",
        "originating_channel": "WEB",
        "trace_id": None,
    }
    for field, expected in stable_fields.items():
        assert before.json()[field] == expected
        assert after.json()[field] == expected
    assert before.json()["request_id"] == before.headers["x-request-id"]
    assert after.json()["request_id"] == after.headers["x-request-id"]
    assert before.json()["request_id"] != after.json()["request_id"]


def test_browser_supplied_identity_role_and_firm_fields_cannot_change_authority(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    response = client.put(
        f"/v1/application-context/active-client/{APOLLO_FINANCE_ID}",
        headers={"Origin": "http://localhost:3000"},
        json={
            "client_id": str(NORTHSTAR_RETAIL_ID),
            "firm_id": str(tenant_data.firm_b.id),
            "user_id": str(tenant_data.bob.id),
            "membership_id": str(tenant_data.bob_membership.id),
            "role": "FIRM_OWNER",
            "granted_capabilities": ["client.read", "client.write"],
        },
    )
    context = client.get("/test/active-client-security-context")

    assert response.status_code == 200
    assert response.json()["active_client"]["id"] == str(APOLLO_FINANCE_ID)
    assert context.json()["user_id"] == str(tenant_data.alice.id)
    assert context.json()["firm_id"] == str(FIRM_A_ID)
    assert context.json()["client_id"] == str(APOLLO_FINANCE_ID)
    assert context.json()["firm_role"] == "CONSULTANT"
    assert context.json()["granted_capabilities"] == ["client.read"]


def test_unauthorized_and_cross_firm_switches_do_not_change_active_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    same_firm = _activate(client, MERIDIAN_RETAIL_ID)
    cross_firm = _activate(client, NORTHSTAR_RETAIL_ID)

    for response in (same_firm, cross_firm):
        assert response.status_code == 404
        assert response.json()["code"] == "RESOURCE_NOT_FOUND"
        assert response.json()["detail"] == "The requested resource could not be found."
    current = client.get("/test/active-client-context")
    assert current.json() == {"client_id": str(APOLLO_FINANCE_ID)}


def test_unknown_and_forbidden_client_identifiers_are_enumeration_resistant(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    responses = [
        _activate(client, MERIDIAN_RETAIL_ID),
        _activate(client, NORTHSTAR_RETAIL_ID),
        _activate(client, uuid4()),
    ]

    assert {
        (response.status_code, response.json()["code"], response.json()["detail"])
        for response in responses
    } == {
        (404, "RESOURCE_NOT_FOUND", "The requested resource could not be found."),
    }
    assert client.get("/test/active-client-context").json() == {"client_id": str(APOLLO_FINANCE_ID)}


def test_active_client_is_scoped_to_validated_member_session(
    tenant_data,
    app_engine: Engine,
) -> None:
    first_tab = _build_client(app_engine, gateway=SessionSpecificGateway())
    second_tab = _build_client(app_engine, gateway=SessionSpecificGateway())
    first_tab.cookies.set("stytch_session", "alice-tab-a")
    second_tab.cookies.set("stytch_session", "alice-tab-b")

    assert _activate(first_tab, APOLLO_FINANCE_ID).status_code == 200
    assert _activate(second_tab, ACME_HEALTHCARE_ID).status_code == 200

    assert first_tab.get("/test/active-client-context").json() == {
        "client_id": str(APOLLO_FINANCE_ID)
    }
    assert second_tab.get("/test/active-client-context").json() == {
        "client_id": str(ACME_HEALTHCARE_ID)
    }


def test_session_selection_is_fingerprinted_not_stored_as_raw_provider_session(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    raw_provider_session = "session-member-test-alice"
    with Session(owner_engine) as session:
        record = session.scalar(select(ActiveClientSession))

    assert record is not None
    assert record.session_fingerprint == session_fingerprint(raw_provider_session)
    assert raw_provider_session not in record.session_fingerprint
    assert len(record.session_fingerprint) == 64


def test_revoked_active_client_is_not_reused(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientAccessGrant)
            .where(ClientAccessGrant.id == ALICE_APOLLO_GRANT_ID)
            .values(status=ClientAccessStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    resolved = client.get("/v1/application-context")
    active_route = client.get("/test/active-client-context")
    assert resolved.status_code == 200
    assert resolved.json()["state"] == "CLIENT_SELECTION_REQUIRED"
    assert resolved.json()["active_client"] is None
    assert active_route.status_code == 404


def test_disabled_active_client_is_not_listed_or_reused(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == APOLLO_FINANCE_ID)
            .values(status=ClientWorkspaceStatus.INACTIVE)
        )

    resolved = client.get("/v1/application-context")
    protected = client.get("/test/active-client-context")

    assert resolved.status_code == 200
    assert resolved.json()["state"] == "CLIENT_SELECTION_REQUIRED"
    assert resolved.json()["active_client"] is None
    assert str(APOLLO_FINANCE_ID) not in resolved.text
    assert "Apollo Finance" not in resolved.text
    assert protected.status_code == 404


def test_revoked_firm_membership_invalidates_context_and_switching(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == tenant_data.alice_membership.id)
            .values(status=MembershipStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    context_response = client.get("/v1/application-context")
    switch_response = _activate(client, ACME_HEALTHCARE_ID)
    protected_response = client.get("/test/active-client-context")

    for response in (context_response, switch_response, protected_response):
        assert response.status_code == 403
        assert response.json()["code"] == "MEMBERSHIP_INACTIVE"


def test_no_authorized_clients_is_an_authenticated_state(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientAccessGrant)
            .where(
                ClientAccessGrant.id.in_(
                    [
                        ALICE_APOLLO_GRANT_ID,
                        ALICE_ACME_GRANT_ID,
                        ALICE_RESTRICTED_GRANT_ID,
                    ]
                )
            )
            .values(status=ClientAccessStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    response = client.get("/v1/application-context")

    assert response.status_code == 200
    assert response.json()["state"] == "NO_AUTHORISED_CLIENTS"
    assert response.json()["active_client"] is None
    assert response.json()["authorised_clients"] == []
    assert response.json()["question_capabilities"] == {
        "can_create": False,
        "can_update": False,
    }


def test_malformed_client_identifier_is_rejected_without_mutation(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    malformed = _activate(client, "not-a-uuid")

    assert malformed.status_code == 422
    assert client.get("/test/active-client-context").json() == {"client_id": str(APOLLO_FINANCE_ID)}


@pytest.mark.parametrize(
    ("session_token", "expected_code"),
    [
        ("expired-token", "SESSION_EXPIRED"),
        ("invalid-token", "AUTHENTICATION_FAILED"),
    ],
)
def test_invalid_or_expired_session_cannot_switch_or_mutate_existing_selection(
    tenant_data,
    app_engine: Engine,
    session_token: str,
    expected_code: str,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    client.cookies.set("stytch_session", session_token)
    rejected = _activate(client, ACME_HEALTHCARE_ID)
    assert rejected.status_code == 401
    assert rejected.json()["code"] == expected_code

    client.cookies.set("stytch_session", "alice-token")
    assert client.get("/test/active-client-context").json() == {"client_id": str(APOLLO_FINANCE_ID)}


def test_logout_revokes_subsequent_application_context_access(
    tenant_data,
    app_engine: Engine,
) -> None:
    gateway = MultiIdentityStytchGateway()
    client = _build_client(app_engine, gateway=gateway)
    client.cookies.set("stytch_session", "alice-token")
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200

    logout = client.post("/v1/auth/logout", headers={"Origin": "http://localhost:3000"})
    context_after_logout = client.get("/v1/application-context")

    assert logout.status_code == 204
    assert "alice-token" in gateway.revoked_tokens
    assert context_after_logout.status_code == 401
    assert context_after_logout.json()["code"] in {
        "AUTHENTICATION_REQUIRED",
        "SESSION_EXPIRED",
    }


def test_authorized_switch_is_idempotent_and_keeps_one_session_selection_row(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")

    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200
    assert _activate(client, APOLLO_FINANCE_ID).status_code == 200
    assert _activate(client, ACME_HEALTHCARE_ID).status_code == 200

    with Session(owner_engine) as session:
        count = session.scalar(select(func.count()).select_from(ActiveClientSession))
        selected = session.scalar(select(ActiveClientSession.active_client_id))

    assert count == 1
    assert selected == ACME_HEALTHCARE_ID


def test_switch_audit_log_contains_safe_ids_without_session_secrets(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = _build_client(app_engine)
    client.cookies.set("stytch_session", "alice-token")
    log_output = io.StringIO()
    capture_handler = logging.StreamHandler(log_output)
    LOGGER.addHandler(capture_handler)

    try:
        assert _activate(client, APOLLO_FINANCE_ID).status_code == 200
        successful_log = log_output.getvalue()
        log_output.seek(0)
        log_output.truncate(0)
        assert _activate(client, NORTHSTAR_RETAIL_ID).status_code == 404
        rejected_log = log_output.getvalue()
    finally:
        LOGGER.removeHandler(capture_handler)

    assert "application_context.client_switched" in successful_log
    assert str(APOLLO_FINANCE_ID) in successful_log
    assert str(tenant_data.alice.id) in successful_log
    assert "alice-token" not in successful_log
    assert "session-member-test-alice" not in successful_log
    assert "application_context.client_switched" not in rejected_log
