from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    CAROL_ID,
    CAROL_MEMBERSHIP_ID,
    DAVID_ID,
    DAVID_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MARK_ID,
    MARK_MEMBERSHIP_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
    VISHANT_ID,
    VISHANT_MEMBERSHIP_ID,
)
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import (
    ClientAccessStatus,
    FirmRole,
    MembershipStatus,
)
from privexa_api.access_control.errors import (
    AuthorizationDeniedError,
    AuthorizationResourceNotFoundError,
)
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.clients.enums import ClientWorkspaceStatus
from privexa_api.clients.models import ClientWorkspace
from privexa_api.clients.repository import ClientWorkspaceRepository
from privexa_api.identity.enums import FirmStatus, UserStatus
from privexa_api.identity.models import Firm, User

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

_PRINCIPAL_MEMBERSHIPS = {
    VISHANT_ID: (VISHANT_MEMBERSHIP_ID, FirmRole.FIRM_OWNER),
    DAVID_ID: (DAVID_MEMBERSHIP_ID, FirmRole.FIRM_ADMIN),
    ALICE_ID: (ALICE_MEMBERSHIP_ID, FirmRole.CONSULTANT),
    CAROL_ID: (CAROL_MEMBERSHIP_ID, FirmRole.REVIEWER),
    MARK_ID: (MARK_MEMBERSHIP_ID, FirmRole.READ_ONLY),
    BOB_ID: (BOB_MEMBERSHIP_ID, FirmRole.CONSULTANT),
}


def _principal(user_id, firm_id) -> AuthenticatedPrincipal:
    membership_id, role = _PRINCIPAL_MEMBERSHIPS[user_id]
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


def _resolve(app_engine: Engine, user_id, firm_id, client_id):
    with Session(app_engine) as session, session.begin():
        authorization = AccessControlService.authorize_client(
            session,
            principal=_principal(user_id, firm_id),
            client_id=client_id,
            permission=Permission.CLIENT_READ,
        )
        return authorization.client_context


def _assert_denied(app_engine: Engine, user_id, firm_id, client_id) -> None:
    with pytest.raises(AuthorizationResourceNotFoundError):
        _resolve(app_engine, user_id, firm_id, client_id)


def _assert_forbidden(app_engine: Engine, user_id, firm_id, client_id) -> None:
    with pytest.raises(AuthorizationDeniedError):
        _resolve(app_engine, user_id, firm_id, client_id)


@pytest.mark.parametrize(
    ("actor", "user_id", "firm_id", "client_id", "expected_role"),
    [
        ("owner-apollo", VISHANT_ID, FIRM_A_ID, APOLLO_FINANCE_ID, FirmRole.FIRM_OWNER),
        ("owner-acme", VISHANT_ID, FIRM_A_ID, ACME_HEALTHCARE_ID, FirmRole.FIRM_OWNER),
        ("owner-meridian", VISHANT_ID, FIRM_A_ID, MERIDIAN_RETAIL_ID, FirmRole.FIRM_OWNER),
        ("admin-apollo", DAVID_ID, FIRM_A_ID, APOLLO_FINANCE_ID, FirmRole.FIRM_ADMIN),
        ("admin-acme", DAVID_ID, FIRM_A_ID, ACME_HEALTHCARE_ID, FirmRole.FIRM_ADMIN),
        ("admin-meridian", DAVID_ID, FIRM_A_ID, MERIDIAN_RETAIL_ID, FirmRole.FIRM_ADMIN),
        ("consultant-apollo", ALICE_ID, FIRM_A_ID, APOLLO_FINANCE_ID, FirmRole.CONSULTANT),
        ("consultant-acme", ALICE_ID, FIRM_A_ID, ACME_HEALTHCARE_ID, FirmRole.CONSULTANT),
        ("reviewer-apollo", CAROL_ID, FIRM_A_ID, APOLLO_FINANCE_ID, FirmRole.REVIEWER),
        ("read-only-acme", MARK_ID, FIRM_A_ID, ACME_HEALTHCARE_ID, FirmRole.READ_ONLY),
        ("firm-b-consultant", BOB_ID, FIRM_B_ID, NORTHSTAR_RETAIL_ID, FirmRole.CONSULTANT),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_allowed_client_authorization_matrix(
    tenant_data,
    app_engine: Engine,
    actor,
    user_id,
    firm_id,
    client_id,
    expected_role,
) -> None:
    context = _resolve(app_engine, user_id, firm_id, client_id)

    assert context.user_id == user_id
    assert context.firm_id == firm_id
    assert context.client_id == client_id
    assert context.role == expected_role


@pytest.mark.parametrize(
    ("actor", "user_id", "firm_id", "client_id"),
    [
        ("owner-foreign-client", VISHANT_ID, FIRM_A_ID, NORTHSTAR_RETAIL_ID),
        ("admin-foreign-client", DAVID_ID, FIRM_A_ID, NORTHSTAR_RETAIL_ID),
        ("consultant-unassigned", ALICE_ID, FIRM_A_ID, MERIDIAN_RETAIL_ID),
        ("consultant-foreign-client", ALICE_ID, FIRM_A_ID, NORTHSTAR_RETAIL_ID),
        ("reviewer-unassigned-acme", CAROL_ID, FIRM_A_ID, ACME_HEALTHCARE_ID),
        ("reviewer-unassigned-meridian", CAROL_ID, FIRM_A_ID, MERIDIAN_RETAIL_ID),
        ("reviewer-foreign-client", CAROL_ID, FIRM_A_ID, NORTHSTAR_RETAIL_ID),
        ("read-only-unassigned", MARK_ID, FIRM_A_ID, APOLLO_FINANCE_ID),
        ("read-only-foreign-client", MARK_ID, FIRM_A_ID, NORTHSTAR_RETAIL_ID),
        ("firm-b-consultant-foreign-client", BOB_ID, FIRM_B_ID, APOLLO_FINANCE_ID),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_denied_client_authorization_matrix(
    tenant_data,
    app_engine: Engine,
    actor,
    user_id,
    firm_id,
    client_id,
) -> None:
    _assert_denied(app_engine, user_id, firm_id, client_id)


def test_forged_principal_for_firm_without_membership_is_forbidden(
    tenant_data,
    app_engine: Engine,
) -> None:
    _assert_forbidden(app_engine, ALICE_ID, FIRM_B_ID, NORTHSTAR_RETAIL_ID)


def test_owner_and_admin_require_no_assignment_rows(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with Session(owner_engine) as session:
        grant_count = session.scalar(
            select(func.count())
            .select_from(ClientAccessGrant)
            .where(
                ClientAccessGrant.membership_id.in_([VISHANT_MEMBERSHIP_ID, DAVID_MEMBERSHIP_ID])
            )
        )

    assert grant_count == 0


def test_rls_fails_closed_without_context(tenant_data, app_engine: Engine) -> None:
    with Session(app_engine) as session:
        clients = session.scalars(select(ClientWorkspace)).all()
        grants = session.scalars(select(ClientAccessGrant)).all()

    assert clients == []
    assert grants == []


def test_rls_scope_is_transaction_local(tenant_data, app_engine: Engine) -> None:
    _resolve(app_engine, ALICE_ID, FIRM_A_ID, APOLLO_FINANCE_ID)

    with Session(app_engine) as session:
        visible_after_transaction = session.scalar(
            select(func.count()).select_from(ClientWorkspace)
        )

    assert visible_after_transaction == 0


def test_authorized_context_drives_tenant_scoped_repository(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        authorization = AccessControlService.authorize_client(
            session,
            principal=_principal(ALICE_ID, FIRM_A_ID),
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_READ,
        )
        context = authorization.client_context
        client = ClientWorkspaceRepository.get_active(session, context=context)
        assert client is not None
        assert client.id == APOLLO_FINANCE_ID
        assert client.firm_id == FIRM_A_ID


@pytest.mark.parametrize(
    ("membership_id", "user_id"),
    [
        (ALICE_MEMBERSHIP_ID, ALICE_ID),
        (DAVID_MEMBERSHIP_ID, DAVID_ID),
        (VISHANT_MEMBERSHIP_ID, VISHANT_ID),
    ],
)
def test_inactive_membership_denies_every_role(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    membership_id,
    user_id,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(FirmMembership)
            .where(FirmMembership.id == membership_id)
            .values(status=MembershipStatus.SUSPENDED)
        )

    _assert_forbidden(app_engine, user_id, FIRM_A_ID, APOLLO_FINANCE_ID)


def test_revoked_assignment_denies_assigned_client(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientAccessGrant)
            .where(
                ClientAccessGrant.membership_id == ALICE_MEMBERSHIP_ID,
                ClientAccessGrant.client_id == APOLLO_FINANCE_ID,
            )
            .values(status=ClientAccessStatus.REVOKED, revoked_at=datetime.now(UTC))
        )

    _assert_denied(app_engine, ALICE_ID, FIRM_A_ID, APOLLO_FINANCE_ID)


def test_suspended_firm_denies_admin_access(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(Firm).where(Firm.id == FIRM_A_ID).values(status=FirmStatus.SUSPENDED)
        )

    _assert_forbidden(app_engine, DAVID_ID, FIRM_A_ID, APOLLO_FINANCE_ID)


def test_disabled_user_denies_otherwise_valid_access(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(update(User).where(User.id == ALICE_ID).values(status=UserStatus.DISABLED))

    _assert_forbidden(app_engine, ALICE_ID, FIRM_A_ID, APOLLO_FINANCE_ID)


@pytest.mark.parametrize(
    ("status", "archived_at"),
    [
        (ClientWorkspaceStatus.INACTIVE, None),
        (ClientWorkspaceStatus.ARCHIVED, datetime.now(UTC)),
    ],
)
def test_inactive_or_archived_client_denies_owner_access(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    status,
    archived_at,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == APOLLO_FINANCE_ID)
            .values(status=status, archived_at=archived_at)
        )

    _assert_denied(app_engine, VISHANT_ID, FIRM_A_ID, APOLLO_FINANCE_ID)


def test_role_is_scoped_to_selected_firm_membership(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    multi_firm_user_id = uuid4()
    firm_a_membership_id = uuid4()
    firm_b_membership_id = uuid4()
    zenith_client_id = uuid4()
    northstar_grant_id = uuid4()

    with Session(owner_engine) as session, session.begin():
        session.add(
            User(
                id=multi_firm_user_id,
                email="multi-firm-user@example.test",
                display_name="Multi Firm User",
            )
        )
        session.flush()
        session.add_all(
            [
                FirmMembership(
                    id=firm_a_membership_id,
                    firm_id=FIRM_A_ID,
                    user_id=multi_firm_user_id,
                    role=FirmRole.FIRM_ADMIN,
                ),
                FirmMembership(
                    id=firm_b_membership_id,
                    firm_id=FIRM_B_ID,
                    user_id=multi_firm_user_id,
                    role=FirmRole.CONSULTANT,
                ),
                ClientWorkspace(
                    id=zenith_client_id,
                    firm_id=FIRM_B_ID,
                    name="Zenith Insurance",
                ),
            ]
        )
        session.flush()
        session.add(
            ClientAccessGrant(
                id=northstar_grant_id,
                firm_id=FIRM_B_ID,
                client_id=NORTHSTAR_RETAIL_ID,
                membership_id=firm_b_membership_id,
            )
        )

    firm_a_principal = AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=multi_firm_user_id,
            membership_id=firm_a_membership_id,
            firm_id=FIRM_A_ID,
            role=FirmRole.FIRM_ADMIN,
        ),
        stytch_member_id="member-multi-firm-a",
        stytch_organization_id="organization-multi-firm-a",
        stytch_member_session_id="session-multi-firm-a",
    )
    firm_b_principal = AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=multi_firm_user_id,
            membership_id=firm_b_membership_id,
            firm_id=FIRM_B_ID,
            role=FirmRole.CONSULTANT,
        ),
        stytch_member_id="member-multi-firm-b",
        stytch_organization_id="organization-multi-firm-b",
        stytch_member_session_id="session-multi-firm-b",
    )

    with Session(app_engine) as session, session.begin():
        firm_a_context = AccessControlService.authorize_client(
            session,
            principal=firm_a_principal,
            client_id=MERIDIAN_RETAIL_ID,
            permission=Permission.CLIENT_READ,
        ).client_context
    with Session(app_engine) as session, session.begin():
        firm_b_context = AccessControlService.authorize_client(
            session,
            principal=firm_b_principal,
            client_id=NORTHSTAR_RETAIL_ID,
            permission=Permission.CLIENT_READ,
        ).client_context

    assert firm_a_context.role == FirmRole.FIRM_ADMIN
    assert firm_a_context.membership_id == firm_a_membership_id
    assert firm_b_context.role == FirmRole.CONSULTANT
    assert firm_b_context.membership_id == firm_b_membership_id
    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(AuthorizationResourceNotFoundError),
    ):
        AccessControlService.authorize_client(
            session,
            principal=firm_b_principal,
            client_id=zenith_client_id,
            permission=Permission.CLIENT_READ,
        )
