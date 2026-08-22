from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    ANITA_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.errors import AuthorizationDeniedError
from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.api.authorization_dependencies import (
    require_firm_permission,
    require_switch_target_client_permission,
)
from privexa_api.api.dependencies import get_database_session
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.clients.service import ClientWorkspaceService
from privexa_api.config import Settings
from privexa_api.db.errors import TenantContextConflictError
from privexa_api.db.session import build_session_factory
from privexa_api.db.tenant_scope import (
    TenantContextStage,
    get_tenant_database_context,
    require_matching_execution_context_scope,
)
from privexa_api.main import create_app
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext, issue_execution_context

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

ClientReadExecution = Annotated[
    ExecutionContext,
    Depends(require_switch_target_client_permission(Permission.CLIENT_READ)),
]
FirmReadExecution = Annotated[
    ExecutionContext,
    Depends(require_firm_permission(Permission.FIRM_READ)),
]
DatabaseSession = Annotated[Session, Depends(get_database_session)]


def _settings() -> Settings:
    return Settings(
        APP_DATABASE_URL="postgresql+psycopg://unused",
        STYTCH_PROJECT_ID="project-test-privexa",
        STYTCH_SECRET=SecretStr("secret-test-privexa"),
        PRIVEXA_ENVIRONMENT="test",
        PRIVEXA_WEB_ORIGIN="http://localhost:3000",
    )


def _context_payload(
    *,
    context: ExecutionContext,
    session: Session,
    client_name: str | None,
) -> dict[str, object]:
    database_context = require_matching_execution_context_scope(session, context)
    settings = session.execute(
        text(
            "SELECT "
            "current_setting('privexa.user_id', true) AS user_id, "
            "current_setting('privexa.membership_id', true) AS membership_id, "
            "current_setting('privexa.firm_id', true) AS firm_id, "
            "current_setting('privexa.client_id', true) AS client_id"
        )
    ).one()
    return {
        "request_id": str(context.request_id),
        "trace_id": context.trace_id,
        "user_id": str(context.user_id),
        "membership_id": str(context.membership_id),
        "firm_id": str(context.firm_id),
        "client_id": str(context.client_id) if context.client_id is not None else None,
        "firm_role": context.firm_role.value,
        "authorization_scope": context.authorization_scope.value,
        "granted_capabilities": sorted(
            capability.value for capability in context.granted_capabilities
        ),
        "effective_sensitivity": context.effective_sensitivity.value,
        "originating_channel": context.originating_channel.value,
        "client_name": client_name,
        "database_stage": database_context.stage.value,
        "database_user_id": settings.user_id,
        "database_membership_id": settings.membership_id,
        "database_firm_id": settings.firm_id,
        "database_client_id": settings.client_id or None,
    }


def _build_app(app_engine: Engine):
    app = create_app(
        settings=_settings(),
        stytch_gateway=MultiIdentityStytchGateway(),
        session_factory=build_session_factory(app_engine),
    )

    @app.get("/test/execution/firm")
    def inspect_firm_context(
        context: FirmReadExecution,
        session: DatabaseSession,
    ) -> dict[str, object]:
        return _context_payload(context=context, session=session, client_name=None)

    @app.get("/test/execution/clients/{client_id}")
    def inspect_client_context(
        context: ClientReadExecution,
        session: DatabaseSession,
    ) -> dict[str, object]:
        client = ClientWorkspaceService.get_current(session, context=context)
        return _context_payload(context=context, session=session, client_name=client.name)

    @app.post("/test/execution/clients/{client_id}")
    def inspect_client_context_with_untrusted_body(
        payload: dict[str, object],
        context: ClientReadExecution,
        session: DatabaseSession,
    ) -> dict[str, object]:
        del payload
        client = ClientWorkspaceService.get_current(session, context=context)
        return _context_payload(context=context, session=session, client_name=client.name)

    @app.post("/test/execution/clients/{client_id}/restricted")
    def inspect_restricted_context_with_untrusted_body(
        payload: dict[str, object],
        context: ClientReadExecution,
        session: DatabaseSession,
    ) -> dict[str, object]:
        del payload
        restricted_context = context.with_minimum_sensitivity(SensitivityLevel.RESTRICTED)
        client = ClientWorkspaceService.get_current(session, context=restricted_context)
        return _context_payload(
            context=restricted_context,
            session=session,
            client_name=client.name,
        )

    return app


def _principal(
    *,
    user_id: UUID,
    membership_id: UUID,
    firm_id: UUID,
    role: FirmRole,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=user_id,
            membership_id=membership_id,
            firm_id=firm_id,
            role=role,
        ),
        stytch_member_id=f"member-{user_id}",
        stytch_organization_id=f"organization-{firm_id}",
        stytch_member_session_id=f"session-{user_id}",
    )


def _issue_client_context(
    app_engine: Engine,
    *,
    principal: AuthenticatedPrincipal,
    client_id: UUID,
) -> ExecutionContext:
    with Session(app_engine) as session, session.begin():
        authorization = AccessControlService.authorize_client(
            session,
            principal=principal,
            client_id=client_id,
            permission=Permission.CLIENT_READ,
        )
        return issue_execution_context(
            authorization=authorization,
            request_id=uuid4(),
            trace_id=None,
            effective_sensitivity=SensitivityLevel.STANDARD,
            originating_channel=OriginatingChannel.WEB,
        )


def test_authenticated_request_propagates_exact_context_into_service_and_rls(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "alice-token")

    response = client.get(f"/test/execution/clients/{APOLLO_FINANCE_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "request_id": response.headers["x-request-id"],
        "trace_id": None,
        "user_id": str(ALICE_ID),
        "membership_id": str(ALICE_MEMBERSHIP_ID),
        "firm_id": str(FIRM_A_ID),
        "client_id": str(APOLLO_FINANCE_ID),
        "firm_role": FirmRole.CONSULTANT.value,
        "authorization_scope": AuthorizationScope.CLIENT.value,
        "granted_capabilities": [Permission.CLIENT_READ.value],
        "effective_sensitivity": SensitivityLevel.STANDARD.value,
        "originating_channel": OriginatingChannel.WEB.value,
        "client_name": "Apollo Finance",
        "database_stage": TenantContextStage.CLIENT.value,
        "database_user_id": str(ALICE_ID),
        "database_membership_id": str(ALICE_MEMBERSHIP_ID),
        "database_firm_id": str(FIRM_A_ID),
        "database_client_id": str(APOLLO_FINANCE_ID),
    }


def test_browser_authority_origin_sensitivity_and_trace_claims_are_ignored(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "anita-token")
    forged_request_id = "00000000-0000-4000-8000-000000000999"

    response = client.post(
        f"/test/execution/clients/{APOLLO_FINANCE_ID}",
        params={
            "user_id": str(BOB_ID),
            "firm_id": str(FIRM_B_ID),
            "client_id": str(NORTHSTAR_RETAIL_ID),
            "role": FirmRole.FIRM_OWNER.value,
            "capability": "DELETE",
            "originating_channel": "SYSTEM",
            "effective_sensitivity": "STANDARD",
        },
        headers={
            "Origin": "http://localhost:3000",
            "X-Request-ID": forged_request_id,
            "X-User-ID": str(BOB_ID),
            "X-Firm-ID": str(FIRM_B_ID),
            "X-Client-ID": str(NORTHSTAR_RETAIL_ID),
            "X-Role": FirmRole.FIRM_OWNER.value,
            "X-Capabilities": "READ_CONTEXT,DELETE,CROSS_CLIENT",
            "X-Originating-Channel": "SYSTEM",
            "X-Sensitivity-Classification": "PUBLIC",
            "X-Trace-ID": "f" * 32,
            "traceparent": "00-ffffffffffffffffffffffffffffffff-ffffffffffffffff-01",
        },
        json={
            "user_id": str(BOB_ID),
            "membership_id": str(BOB_MEMBERSHIP_ID),
            "firm_id": str(FIRM_B_ID),
            "client_id": str(NORTHSTAR_RETAIL_ID),
            "role": FirmRole.FIRM_OWNER.value,
            "granted_capabilities": ["DELETE", "CROSS_CLIENT"],
            "originating_channel": "SYSTEM",
            "effective_sensitivity": "STANDARD",
            "trace_id": "f" * 32,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == str(ANITA_ID)
    assert payload["firm_id"] == str(FIRM_A_ID)
    assert payload["client_id"] == str(APOLLO_FINANCE_ID)
    assert payload["firm_role"] == FirmRole.CONSULTANT.value
    assert payload["granted_capabilities"] == [Permission.CLIENT_READ.value]
    assert payload["originating_channel"] == OriginatingChannel.WEB.value
    assert payload["effective_sensitivity"] == SensitivityLevel.STANDARD.value
    assert payload["trace_id"] is None
    assert payload["request_id"] != forged_request_id
    assert response.headers["x-request-id"] == payload["request_id"]


def test_client_supplied_standard_cannot_downgrade_restricted_server_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "alice-token")

    response = client.post(
        f"/test/execution/clients/{APOLLO_FINANCE_ID}/restricted",
        params={"sensitivity": "STANDARD", "effective_sensitivity": "STANDARD"},
        headers={
            "Origin": "http://localhost:3000",
            "X-Sensitivity": "STANDARD",
            "X-Effective-Sensitivity": "STANDARD",
        },
        json={
            "sensitivity": "STANDARD",
            "effective_sensitivity": "STANDARD",
        },
    )

    assert response.status_code == 200
    assert response.json()["effective_sensitivity"] == SensitivityLevel.RESTRICTED.value
    assert response.json()["client_id"] == str(APOLLO_FINANCE_ID)


@pytest.mark.parametrize(
    "target_client_id",
    [MERIDIAN_RETAIL_ID, NORTHSTAR_RETAIL_ID],
    ids=["same-firm-unassigned", "cross-firm"],
)
def test_sensitivity_payload_cannot_bypass_client_authorization_or_rls(
    tenant_data,
    app_engine: Engine,
    target_client_id: UUID,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "anita-token")

    response = client.post(
        f"/test/execution/clients/{target_client_id}/restricted",
        headers={"Origin": "http://localhost:3000"},
        json={
            "sensitivity": "STANDARD",
            "effective_sensitivity": "STANDARD",
            "client_id": str(target_client_id),
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert "sensitivity" not in response.text.lower()


@pytest.mark.parametrize("token", [None, "invalid-token", "expired-token"])
def test_restricted_context_route_cannot_be_reached_without_valid_authentication(
    tenant_data,
    app_engine: Engine,
    token: str | None,
) -> None:
    client = TestClient(_build_app(app_engine))
    if token is not None:
        client.cookies.set("stytch_session", token)

    response = client.post(
        f"/test/execution/clients/{APOLLO_FINANCE_ID}/restricted",
        headers={"Origin": "http://localhost:3000"},
        json={"effective_sensitivity": "STANDARD"},
    )

    assert response.status_code == 401
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize(
    "token",
    [None, "invalid-token", "expired-token"],
    ids=["missing-session", "invalid-session", "expired-session"],
)
def test_context_is_never_created_without_valid_authentication(
    tenant_data,
    app_engine: Engine,
    token: str | None,
) -> None:
    client = TestClient(_build_app(app_engine))
    if token is not None:
        client.cookies.set("stytch_session", token)

    response = client.get(f"/test/execution/clients/{APOLLO_FINANCE_ID}")

    assert response.status_code == 401
    assert response.json()["code"] in {
        "AUTHENTICATION_REQUIRED",
        "AUTHENTICATION_FAILED",
        "SESSION_EXPIRED",
    }
    assert "capabil" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def test_valid_provider_identity_without_membership_cannot_create_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "unprovisioned-token")

    response = client.get(f"/test/execution/clients/{APOLLO_FINANCE_ID}")

    assert response.status_code == 403
    assert response.json()["code"] == "MEMBER_NOT_PROVISIONED"
    assert "capabil" not in response.text.lower()


@pytest.mark.parametrize(
    "target_client_id",
    [MERIDIAN_RETAIL_ID, NORTHSTAR_RETAIL_ID],
    ids=["same-firm-unassigned-client", "cross-firm-client"],
)
def test_unauthorized_client_selector_cannot_create_trusted_context(
    tenant_data,
    app_engine: Engine,
    target_client_id: UUID,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "anita-token")

    response = client.get(f"/test/execution/clients/{target_client_id}")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert "Meridian" not in response.text
    assert "Northstar" not in response.text
    assert "permission" not in response.text.lower()


def test_firm_scoped_execution_uses_no_fake_client_identifier(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "anita-token")

    response = client.get(
        "/test/execution/firm",
        headers={"X-Client-ID": str(NORTHSTAR_RETAIL_ID)},
        params={"client_id": str(NORTHSTAR_RETAIL_ID)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["firm_id"] == str(FIRM_A_ID)
    assert payload["client_id"] is None
    assert payload["database_client_id"] is None
    assert payload["authorization_scope"] == AuthorizationScope.FIRM.value
    assert payload["database_stage"] == TenantContextStage.FIRM.value


def test_client_service_rejects_missing_forged_and_firm_scoped_contexts(
    tenant_data,
    app_engine: Engine,
) -> None:
    forged = ExecutionContext(
        request_id=uuid4(),
        trace_id=None,
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        client_id=NORTHSTAR_RETAIL_ID,
        firm_role=FirmRole.FIRM_OWNER,
        authorization_scope=AuthorizationScope.CLIENT,
        granted_capabilities=frozenset({Permission.CLIENT_READ}),
        effective_sensitivity=SensitivityLevel.STANDARD,
        originating_channel=OriginatingChannel.WEB,
    )

    with Session(app_engine) as session:
        with pytest.raises(AuthorizationDeniedError):
            ClientWorkspaceService.get_current(session, context=None)  # type: ignore[arg-type]
        with pytest.raises(AuthorizationDeniedError):
            ClientWorkspaceService.get_current(session, context=forged)
        with pytest.raises(TypeError):
            ClientWorkspaceService.get_current(session)  # type: ignore[call-arg]

    with Session(app_engine) as session, session.begin():
        firm_authorization = AccessControlService.authorize_firm(
            session,
            principal=_principal(
                user_id=ALICE_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
                firm_id=FIRM_A_ID,
                role=FirmRole.CONSULTANT,
            ),
            permission=Permission.FIRM_READ,
        )
        firm_context = issue_execution_context(
            authorization=firm_authorization,
            request_id=uuid4(),
            trace_id=None,
            effective_sensitivity=SensitivityLevel.STANDARD,
            originating_channel=OriginatingChannel.WEB,
        )
        with pytest.raises(AuthorizationDeniedError):
            ClientWorkspaceService.get_current(session, context=firm_context)


def test_request_scoped_context_cannot_be_reused_without_matching_rls_scope(
    tenant_data,
    app_engine: Engine,
) -> None:
    context = _issue_client_context(
        app_engine,
        principal=_principal(
            user_id=ALICE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            role=FirmRole.CONSULTANT,
        ),
        client_id=APOLLO_FINANCE_ID,
    )

    with Session(app_engine) as clean_session, pytest.raises(TenantContextConflictError):
        ClientWorkspaceService.get_current(clean_session, context=context)


def test_context_and_different_final_rls_scope_cannot_be_combined(
    tenant_data,
    app_engine: Engine,
) -> None:
    alice_context = _issue_client_context(
        app_engine,
        principal=_principal(
            user_id=ALICE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            role=FirmRole.CONSULTANT,
        ),
        client_id=APOLLO_FINANCE_ID,
    )

    with Session(app_engine) as bob_session, bob_session.begin():
        AccessControlService.authorize_client(
            bob_session,
            principal=_principal(
                user_id=BOB_ID,
                membership_id=BOB_MEMBERSHIP_ID,
                firm_id=FIRM_B_ID,
                role=FirmRole.CONSULTANT,
            ),
            client_id=NORTHSTAR_RETAIL_ID,
            permission=Permission.CLIENT_READ,
        )
        with pytest.raises(TenantContextConflictError):
            ClientWorkspaceService.get_current(bob_session, context=alice_context)


def test_sequential_requests_do_not_reuse_identity_tenant_or_request_id(
    tenant_data,
    app_engine: Engine,
) -> None:
    client = TestClient(_build_app(app_engine))
    client.cookies.set("stytch_session", "alice-token")
    alice = client.get(f"/test/execution/clients/{APOLLO_FINANCE_ID}")
    client.cookies.set("stytch_session", "bob-token")
    bob = client.get(f"/test/execution/clients/{NORTHSTAR_RETAIL_ID}")

    assert alice.status_code == bob.status_code == 200
    assert alice.json()["user_id"] == str(ALICE_ID)
    assert alice.json()["firm_id"] == str(FIRM_A_ID)
    assert alice.json()["client_id"] == str(APOLLO_FINANCE_ID)
    assert bob.json()["user_id"] == str(BOB_ID)
    assert bob.json()["firm_id"] == str(FIRM_B_ID)
    assert bob.json()["client_id"] == str(NORTHSTAR_RETAIL_ID)
    assert alice.json()["request_id"] != bob.json()["request_id"]


def test_concurrent_requests_keep_execution_and_rls_contexts_isolated(
    tenant_data,
    app_engine: Engine,
) -> None:
    app = _build_app(app_engine)
    alice_client = TestClient(app)
    bob_client = TestClient(app)
    alice_client.cookies.set("stytch_session", "alice-token")
    bob_client.cookies.set("stytch_session", "bob-token")
    barrier = Barrier(2)

    def request(client: TestClient, client_id: UUID) -> dict[str, object]:
        barrier.wait(timeout=5)
        response = client.get(f"/test/execution/clients/{client_id}")
        assert response.status_code == 200
        return response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        alice_future = executor.submit(request, alice_client, APOLLO_FINANCE_ID)
        bob_future = executor.submit(request, bob_client, NORTHSTAR_RETAIL_ID)
        alice = alice_future.result(timeout=10)
        bob = bob_future.result(timeout=10)

    assert alice["user_id"] == alice["database_user_id"] == str(ALICE_ID)
    assert alice["firm_id"] == alice["database_firm_id"] == str(FIRM_A_ID)
    assert alice["client_id"] == alice["database_client_id"] == str(APOLLO_FINANCE_ID)
    assert bob["user_id"] == bob["database_user_id"] == str(BOB_ID)
    assert bob["firm_id"] == bob["database_firm_id"] == str(FIRM_B_ID)
    assert bob["client_id"] == bob["database_client_id"] == str(NORTHSTAR_RETAIL_ID)
    assert alice["request_id"] != bob["request_id"]


def test_context_projection_matches_final_database_scope_exactly(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        authorization = AccessControlService.authorize_client(
            session,
            principal=_principal(
                user_id=ALICE_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
                firm_id=FIRM_A_ID,
                role=FirmRole.CONSULTANT,
            ),
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_READ,
        )
        context = issue_execution_context(
            authorization=authorization,
            request_id=uuid4(),
            trace_id=None,
            effective_sensitivity=SensitivityLevel.STANDARD,
            originating_channel=OriginatingChannel.WEB,
        )

        database_context = get_tenant_database_context(session)
        projection = context.to_client_context()

        assert database_context is not None
        assert database_context.stage == TenantContextStage.CLIENT
        assert projection.user_id == database_context.user_id == context.user_id
        assert projection.membership_id == database_context.membership_id == context.membership_id
        assert projection.firm_id == database_context.firm_id == context.firm_id
        assert projection.client_id == database_context.client_id == context.client_id
