from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    ANITA_ID,
    ANITA_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    DAVID_ID,
    DAVID_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ADMIN_ID,
    FIRM_B_ADMIN_MEMBERSHIP_ID,
    FIRM_B_ID,
    INACTIVE_MEMBER_ID,
    INACTIVE_MEMBERSHIP_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
    RAHUL_ID,
    RAHUL_MEMBERSHIP_ID,
    VISHANT_ID,
    VISHANT_MEMBERSHIP_ID,
)
from sqlalchemy import Engine, delete, update
from sqlalchemy.orm import Session

from privexa_api.access_control.context import ClientContext, FirmContext
from privexa_api.access_control.decisions import AuthorizationFailureReason
from privexa_api.access_control.enums import FirmRole, MembershipStatus
from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationResourceNotFoundError,
)
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.clients.repository import ClientWorkspaceRepository
from privexa_api.clients.service import ClientWorkspaceService

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _principal(
    *,
    user_id,
    membership_id,
    role: FirmRole,
    firm_id=FIRM_A_ID,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=user_id,
            membership_id=membership_id,
            firm_id=firm_id,
            role=role,
        ),
        stytch_member_id=f"member-{user_id}",
        stytch_organization_id="organization-firm-a",
        stytch_member_session_id=f"session-{user_id}",
    )


@pytest.mark.parametrize(
    ("user_id", "membership_id", "role", "firm_id", "client_id", "allowed"),
    [
        (ANITA_ID, ANITA_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, APOLLO_FINANCE_ID, True),
        (ANITA_ID, ANITA_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, ACME_HEALTHCARE_ID, False),
        (RAHUL_ID, RAHUL_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, ACME_HEALTHCARE_ID, True),
        (RAHUL_ID, RAHUL_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, APOLLO_FINANCE_ID, False),
        (ALICE_ID, ALICE_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, APOLLO_FINANCE_ID, True),
        (ALICE_ID, ALICE_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, ACME_HEALTHCARE_ID, True),
        (ALICE_ID, ALICE_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_A_ID, NORTHSTAR_RETAIL_ID, False),
        (DAVID_ID, DAVID_MEMBERSHIP_ID, FirmRole.FIRM_ADMIN, FIRM_A_ID, APOLLO_FINANCE_ID, True),
        (DAVID_ID, DAVID_MEMBERSHIP_ID, FirmRole.FIRM_ADMIN, FIRM_A_ID, MERIDIAN_RETAIL_ID, True),
        (DAVID_ID, DAVID_MEMBERSHIP_ID, FirmRole.FIRM_ADMIN, FIRM_A_ID, NORTHSTAR_RETAIL_ID, False),
        (
            FIRM_B_ADMIN_ID,
            FIRM_B_ADMIN_MEMBERSHIP_ID,
            FirmRole.FIRM_ADMIN,
            FIRM_B_ID,
            NORTHSTAR_RETAIL_ID,
            True,
        ),
        (
            FIRM_B_ADMIN_ID,
            FIRM_B_ADMIN_MEMBERSHIP_ID,
            FirmRole.FIRM_ADMIN,
            FIRM_B_ID,
            APOLLO_FINANCE_ID,
            False,
        ),
        (BOB_ID, BOB_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_B_ID, NORTHSTAR_RETAIL_ID, True),
        (BOB_ID, BOB_MEMBERSHIP_ID, FirmRole.CONSULTANT, FIRM_B_ID, APOLLO_FINANCE_ID, False),
    ],
    ids=[
        "consultant-a1-assigned-a1",
        "consultant-a1-unassigned-a2",
        "consultant-a2-assigned-a2",
        "consultant-a2-unassigned-a1",
        "consultant-a3-assigned-a1",
        "consultant-a3-assigned-a2",
        "consultant-a3-cross-firm-b1",
        "admin-a-client-a1",
        "admin-a-client-a3-without-grant",
        "admin-a-cross-firm-b1",
        "admin-b-client-b1",
        "admin-b-cross-firm-a1",
        "consultant-b1-assigned-b1",
        "consultant-b1-cross-firm-a1",
    ],
)
def test_client_scope_matrix(
    tenant_data,
    app_engine: Engine,
    user_id,
    membership_id,
    role,
    firm_id,
    client_id,
    allowed,
) -> None:
    principal = _principal(
        user_id=user_id,
        membership_id=membership_id,
        role=role,
        firm_id=firm_id,
    )

    if allowed:
        with Session(app_engine) as session, session.begin():
            result = AccessControlService.authorize_client(
                session,
                principal=principal,
                client_id=client_id,
                permission=Permission.CLIENT_READ,
            )
        assert result.client_context.client_id == client_id
    else:
        with (
            Session(app_engine) as session,
            session.begin(),
            pytest.raises(AuthorizationResourceNotFoundError),
        ):
            AccessControlService.authorize_client(
                session,
                principal=principal,
                client_id=client_id,
                permission=Permission.CLIENT_READ,
            )


def test_admin_can_read_every_active_client_without_assignment(
    tenant_data,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=DAVID_ID,
        membership_id=DAVID_MEMBERSHIP_ID,
        role=FirmRole.FIRM_ADMIN,
    )

    for client_id in (APOLLO_FINANCE_ID, ACME_HEALTHCARE_ID, MERIDIAN_RETAIL_ID):
        with Session(app_engine) as session, session.begin():
            authorization = AccessControlService.authorize_client(
                session,
                principal=principal,
                client_id=client_id,
                permission=Permission.CLIENT_READ,
            )
        assert authorization.client_context.client_id == client_id


def test_consultant_is_denied_an_unassigned_client_without_disclosure(
    tenant_data,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        role=FirmRole.CONSULTANT,
    )

    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(AuthorizationResourceNotFoundError) as captured,
    ):
        AccessControlService.authorize_client(
            session,
            principal=principal,
            client_id=MERIDIAN_RETAIL_ID,
            permission=Permission.CLIENT_READ,
        )

    assert captured.value.reason == AuthorizationFailureReason.CLIENT_ACCESS_REQUIRED


def test_consultant_is_forbidden_from_firm_member_management(
    tenant_data,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        role=FirmRole.CONSULTANT,
    )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        AccessControlService.authorize_firm(
            session,
            principal=principal,
            permission=Permission.FIRM_MEMBERS_MANAGE,
        )

    assert captured.value.reason == AuthorizationFailureReason.PERMISSION_DENIED


def test_active_member_can_receive_only_self_profile_authority(
    tenant_data,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        role=FirmRole.CONSULTANT,
    )

    with Session(app_engine) as session:
        authorization = AccessControlService.authorize_self(
            session,
            principal=principal,
            permission=Permission.PROFILE_READ_SELF,
        )

    assert authorization.firm_context.user_id == ALICE_ID
    assert authorization.granted_permission == Permission.PROFILE_READ_SELF


def test_stale_principal_role_fails_closed(tenant_data, app_engine: Engine) -> None:
    stale_principal = _principal(
        user_id=ALICE_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
        role=FirmRole.FIRM_ADMIN,
    )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        AccessControlService.authorize_firm(
            session,
            principal=stale_principal,
            permission=Permission.FIRM_UPDATE,
        )

    assert captured.value.reason == AuthorizationFailureReason.INVALID_CONTEXT


def test_revocation_invalidates_authorization_while_session_identity_can_remain_valid(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=VISHANT_ID,
        membership_id=VISHANT_MEMBERSHIP_ID,
        role=FirmRole.FIRM_OWNER,
    )
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == VISHANT_MEMBERSHIP_ID)
            .values(status=MembershipStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        AccessControlService.authorize_firm(
            session,
            principal=principal,
            permission=Permission.FIRM_READ,
        )

    assert captured.value.reason == AuthorizationFailureReason.FIRM_MEMBERSHIP_INACTIVE


def test_preexisting_inactive_member_is_denied(tenant_data, app_engine: Engine) -> None:
    principal = _principal(
        user_id=INACTIVE_MEMBER_ID,
        membership_id=INACTIVE_MEMBERSHIP_ID,
        role=FirmRole.CONSULTANT,
    )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        AccessControlService.authorize_firm(
            session,
            principal=principal,
            permission=Permission.FIRM_READ,
        )

    assert captured.value.reason == AuthorizationFailureReason.FIRM_MEMBERSHIP_INACTIVE


def test_missing_membership_and_forged_principal_fail_closed(
    tenant_data,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=ANITA_ID,
        membership_id=uuid4(),
        role=FirmRole.FIRM_ADMIN,
    )

    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        AccessControlService.authorize_firm(
            session,
            principal=principal,
            permission=Permission.FIRM_UPDATE,
        )

    assert captured.value.reason == AuthorizationFailureReason.FIRM_MEMBERSHIP_REQUIRED


def test_missing_principal_fails_with_controlled_authorization_denial(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        AccessControlService.authorize_firm(
            session,
            principal=None,  # type: ignore[arg-type]
            permission=Permission.FIRM_READ,
        )

    assert captured.value.reason == AuthorizationFailureReason.INVALID_CONTEXT


def test_nonexistent_and_valid_foreign_client_ids_share_safe_failure(
    tenant_data,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=ANITA_ID,
        membership_id=ANITA_MEMBERSHIP_ID,
        role=FirmRole.CONSULTANT,
    )

    for client_id in (uuid4(), ACME_HEALTHCARE_ID, NORTHSTAR_RETAIL_ID):
        with (
            Session(app_engine) as session,
            session.begin(),
            pytest.raises(AuthorizationResourceNotFoundError) as captured,
        ):
            AccessControlService.authorize_client(
                session,
                principal=principal,
                client_id=client_id,
                permission=Permission.CLIENT_READ,
            )
        assert captured.value.reason == AuthorizationFailureReason.CLIENT_ACCESS_REQUIRED


def test_assignment_reassignment_uses_current_database_state(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    principal = _principal(
        user_id=ANITA_ID,
        membership_id=ANITA_MEMBERSHIP_ID,
        role=FirmRole.CONSULTANT,
    )
    with Session(app_engine) as session, session.begin():
        AccessControlService.authorize_client(
            session,
            principal=principal,
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_READ,
        )
    with Session(owner_engine) as session, session.begin():
        session.execute(
            delete(ClientAccessGrant).where(ClientAccessGrant.membership_id == ANITA_MEMBERSHIP_ID)
        )
        session.add(
            ClientAccessGrant(
                id=uuid4(),
                firm_id=FIRM_A_ID,
                client_id=ACME_HEALTHCARE_ID,
                membership_id=ANITA_MEMBERSHIP_ID,
            )
        )

    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(AuthorizationResourceNotFoundError),
    ):
        AccessControlService.authorize_client(
            session,
            principal=principal,
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_READ,
        )
    with Session(app_engine) as session, session.begin():
        reassigned = AccessControlService.authorize_client(
            session,
            principal=principal,
            client_id=ACME_HEALTHCARE_ID,
            permission=Permission.CLIENT_READ,
        )
    assert reassigned.client_context.client_id == ACME_HEALTHCARE_ID


@pytest.mark.parametrize("bad_context", [None, object()])
def test_direct_service_call_with_invalid_context_is_denied_not_crashed(
    tenant_data,
    app_engine: Engine,
    bad_context,
) -> None:
    with Session(app_engine) as session, pytest.raises(AuthorizationDeniedError) as captured:
        ClientWorkspaceService.get_current(
            session,
            authorization=bad_context,
        )

    assert captured.value.reason == AuthorizationFailureReason.INVALID_CONTEXT


def test_repository_query_rejects_valid_client_uuid_with_mismatched_firm_scope(
    tenant_data,
    owner_engine: Engine,
) -> None:
    inconsistent_context = ClientContext(
        user_id=ANITA_ID,
        membership_id=ANITA_MEMBERSHIP_ID,
        firm_id=FIRM_A_ID,
        client_id=NORTHSTAR_RETAIL_ID,
        role=FirmRole.CONSULTANT,
    )

    with Session(owner_engine) as session:
        result = ClientWorkspaceRepository.get_active(
            session,
            context=inconsistent_context,
        )

    assert result is None
