from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fixtures.security import (
    MockAgentInvocation,
    MockExecutionContext,
    MockPrivexaAgentExecutor,
    MockPrivexaToolExecutor,
    MockToolCall,
)
from fixtures.tenant_foundation import (
    ALICE_APOLLO_GRANT_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    FIRM_A_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine, update
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import ClientAccessStatus, FirmRole, MembershipStatus
from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationResourceNotFoundError,
)
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.authentication.principal import AuthenticatedPrincipal

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _alice_principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=ALICE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            role=FirmRole.CONSULTANT,
        ),
        stytch_member_id="member-test-alice",
        stytch_organization_id="organization-test-firm-a",
        stytch_member_session_id="session-member-test-alice",
    )


def _apollo_execution_context() -> MockExecutionContext:
    return MockExecutionContext(
        principal=_alice_principal(),
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
    )


def _get_client_call(resource_id) -> MockToolCall:
    return MockToolCall(tool_name="get_client_workspace", resource_id=resource_id)


def test_ai_tool_allows_authorized_same_client_resource(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        resource = MockPrivexaToolExecutor.execute(
            session,
            context=_apollo_execution_context(),
            call=_get_client_call(APOLLO_FINANCE_ID),
        )

    assert resource.resource_id == APOLLO_FINANCE_ID
    assert resource.name == "Apollo Finance"


@pytest.mark.parametrize(
    "foreign_resource_id",
    [MERIDIAN_RETAIL_ID, NORTHSTAR_RETAIL_ID],
    ids=["same-firm-unassigned-client", "cross-firm-client"],
)
def test_ai_tool_cannot_convert_foreign_resource_id_into_authority(
    tenant_data,
    app_engine: Engine,
    foreign_resource_id,
) -> None:
    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(AuthorizationResourceNotFoundError),
    ):
        MockPrivexaToolExecutor.execute(
            session,
            context=_apollo_execution_context(),
            call=_get_client_call(foreign_resource_id),
        )


def test_ai_tool_rejects_forged_firm_in_execution_context(
    tenant_data,
    app_engine: Engine,
) -> None:
    forged_context = MockExecutionContext(
        principal=_alice_principal(),
        firm_id=tenant_data.firm_b.id,
        client_id=APOLLO_FINANCE_ID,
    )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError):
        MockPrivexaToolExecutor.execute(
            session,
            context=forged_context,
            call=_get_client_call(APOLLO_FINANCE_ID),
        )


def test_agent_allows_authorized_same_client_resource(
    tenant_data,
    app_engine: Engine,
) -> None:
    invocation = MockAgentInvocation(
        execution_context=_apollo_execution_context(),
        tool_call=_get_client_call(APOLLO_FINANCE_ID),
    )

    with Session(app_engine) as session, session.begin():
        resource = MockPrivexaAgentExecutor.execute(session, invocation=invocation)

    assert resource.resource_id == APOLLO_FINANCE_ID


def test_agent_cannot_access_cross_firm_resource_by_known_uuid(
    tenant_data,
    app_engine: Engine,
) -> None:
    invocation = MockAgentInvocation(
        execution_context=_apollo_execution_context(),
        tool_call=_get_client_call(NORTHSTAR_RETAIL_ID),
    )

    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(AuthorizationResourceNotFoundError),
    ):
        MockPrivexaAgentExecutor.execute(session, invocation=invocation)


def test_agent_rechecks_assignment_when_execution_begins(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    invocation = MockAgentInvocation(
        execution_context=_apollo_execution_context(),
        tool_call=_get_client_call(APOLLO_FINANCE_ID),
    )
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientAccessGrant)
            .where(ClientAccessGrant.id == ALICE_APOLLO_GRANT_ID)
            .values(status=ClientAccessStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(AuthorizationResourceNotFoundError),
    ):
        MockPrivexaAgentExecutor.execute(session, invocation=invocation)


def test_agent_rechecks_membership_when_execution_begins(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    invocation = MockAgentInvocation(
        execution_context=_apollo_execution_context(),
        tool_call=_get_client_call(APOLLO_FINANCE_ID),
    )
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
            .values(status=MembershipStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError):
        MockPrivexaAgentExecutor.execute(session, invocation=invocation)
