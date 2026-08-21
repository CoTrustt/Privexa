from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_APOLLO_GRANT_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    CAROL_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import ClientAccessStatus, FirmRole, MembershipStatus
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.clients.models import ClientWorkspace
from privexa_api.db.tenant_scope import apply_requested_client_scope
from privexa_api.identity.models import Firm, User


def test_client_ownership_and_multiple_clients_per_firm(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with Session(owner_engine) as session:
        firm_a_clients = session.scalars(
            select(ClientWorkspace).where(ClientWorkspace.firm_id == FIRM_A_ID)
        ).all()
        northstar = session.get(ClientWorkspace, NORTHSTAR_RETAIL_ID)

    assert {client.name for client in firm_a_clients} == {
        "Apollo Finance",
        "Acme Healthcare",
        "Meridian Retail",
    }
    assert northstar is not None
    assert northstar.firm_id == FIRM_B_ID


def test_client_with_nonexistent_firm_is_rejected(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(ClientWorkspace(id=uuid4(), firm_id=uuid4(), name="Orphan Client"))
        session.flush()


def test_user_is_not_owned_by_one_firm_and_firm_has_no_login_fields() -> None:
    assert "firm_id" not in User.__table__.c
    assert {"username", "password", "password_hash", "login"}.isdisjoint(Firm.__table__.c)


def test_same_user_can_have_memberships_in_different_firms(
    tenant_data,
    owner_engine: Engine,
) -> None:
    second_membership_id = uuid4()
    with Session(owner_engine) as session, session.begin():
        session.add(
            FirmMembership(
                id=second_membership_id,
                firm_id=FIRM_B_ID,
                user_id=ALICE_ID,
                role=FirmRole.REVIEWER,
            )
        )

    with Session(owner_engine) as session:
        memberships = session.scalars(
            select(FirmMembership).where(FirmMembership.user_id == ALICE_ID)
        ).all()

    assert {(membership.firm_id, membership.role) for membership in memberships} == {
        (FIRM_A_ID, FirmRole.CONSULTANT),
        (FIRM_B_ID, FirmRole.REVIEWER),
    }


def test_duplicate_membership_is_rejected(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(
            FirmMembership(
                id=uuid4(),
                firm_id=FIRM_A_ID,
                user_id=ALICE_ID,
                role=FirmRole.REVIEWER,
            )
        )
        session.flush()


@pytest.mark.parametrize("missing_reference", ["user", "firm"])
def test_membership_invalid_reference_is_rejected(
    tenant_data,
    owner_engine: Engine,
    missing_reference: str,
) -> None:
    user_id = uuid4() if missing_reference == "user" else ALICE_ID
    firm_id = uuid4() if missing_reference == "firm" else FIRM_B_ID

    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(
            FirmMembership(
                id=uuid4(),
                firm_id=firm_id,
                user_id=user_id,
                role=FirmRole.CONSULTANT,
            )
        )
        session.flush()


def test_valid_client_assignment_can_be_created_and_retrieved(
    tenant_data,
    owner_engine: Engine,
) -> None:
    grant_id = uuid4()
    with Session(owner_engine) as session, session.begin():
        session.add(
            ClientAccessGrant(
                id=grant_id,
                firm_id=FIRM_A_ID,
                membership_id=CAROL_MEMBERSHIP_ID,
                client_id=ACME_HEALTHCARE_ID,
            )
        )

    with Session(owner_engine) as session:
        grant = session.get(ClientAccessGrant, grant_id)

    assert grant is not None
    assert grant.firm_id == FIRM_A_ID
    assert grant.membership_id == CAROL_MEMBERSHIP_ID
    assert grant.client_id == ACME_HEALTHCARE_ID


def test_duplicate_client_assignment_is_rejected(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(
            ClientAccessGrant(
                id=uuid4(),
                firm_id=FIRM_A_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
                client_id=APOLLO_FINANCE_ID,
            )
        )
        session.flush()


@pytest.mark.parametrize(
    ("firm_id", "membership_id", "client_id"),
    [
        (FIRM_A_ID, ALICE_MEMBERSHIP_ID, NORTHSTAR_RETAIL_ID),
        (FIRM_B_ID, ALICE_MEMBERSHIP_ID, NORTHSTAR_RETAIL_ID),
    ],
)
def test_cross_firm_client_assignment_is_rejected_by_composite_foreign_keys(
    tenant_data,
    owner_engine: Engine,
    firm_id,
    membership_id,
    client_id,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.add(
            ClientAccessGrant(
                id=uuid4(),
                firm_id=firm_id,
                membership_id=membership_id,
                client_id=client_id,
            )
        )
        session.flush()


@pytest.mark.parametrize("null_column", ["firm_id", "client_id", "membership_id"])
def test_client_assignment_requires_all_ownership_columns(
    tenant_data,
    owner_engine: Engine,
    null_column: str,
) -> None:
    values = {
        "firm_id": FIRM_A_ID,
        "client_id": APOLLO_FINANCE_ID,
        "membership_id": ALICE_MEMBERSHIP_ID,
    }
    values[null_column] = None
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO client_access_grants "
                "(id, firm_id, client_id, membership_id, status) "
                "VALUES (:id, :firm_id, :client_id, :membership_id, 'ACTIVE')"
            ),
            {"id": uuid4(), **values},
        )


def test_unknown_role_is_rejected_by_database_constraint(
    tenant_data,
    owner_engine: Engine,
) -> None:
    new_user_id = uuid4()
    with Session(owner_engine) as session, session.begin():
        session.add(
            User(
                id=new_user_id,
                email=f"{new_user_id}@example.test",
                display_name="Unknown Role User",
            )
        )

    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO firm_memberships "
                "(id, firm_id, user_id, role, status) "
                "VALUES (:id, :firm_id, :user_id, 'UNKNOWN', 'ACTIVE')"
            ),
            {"id": uuid4(), "firm_id": FIRM_A_ID, "user_id": new_user_id},
        )


@pytest.mark.parametrize(
    ("table_name", "identifier", "status"),
    [
        ("firm_memberships", ALICE_MEMBERSHIP_ID, MembershipStatus.REVOKED.value),
        (
            "client_access_grants",
            ALICE_APOLLO_GRANT_ID,
            ClientAccessStatus.REVOKED.value,
        ),
    ],
)
def test_revoked_lifecycle_requires_timestamp(
    tenant_data,
    owner_engine: Engine,
    table_name: str,
    identifier,
    status: str,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.execute(
            text(f"UPDATE {table_name} SET status = :status WHERE id = :identifier"),
            {"status": status, "identifier": identifier},
        )


def test_archived_client_requires_timestamp(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.execute(
            text("UPDATE client_workspaces SET status = 'ARCHIVED' WHERE id = :identifier"),
            {"identifier": APOLLO_FINANCE_ID},
        )


def test_one_membership_can_have_multiple_clients_and_one_client_multiple_members(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with Session(owner_engine) as session:
        alice_grants = session.scalar(
            select(func.count())
            .select_from(ClientAccessGrant)
            .where(ClientAccessGrant.membership_id == ALICE_MEMBERSHIP_ID)
        )
        apollo_explicit_members = session.scalar(
            select(func.count())
            .select_from(ClientAccessGrant)
            .where(ClientAccessGrant.client_id == APOLLO_FINANCE_ID)
        )

    assert alice_grants == 2
    assert apollo_explicit_members == 3


def test_client_display_name_is_not_globally_unique(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        session.add_all(
            [
                ClientWorkspace(id=uuid4(), firm_id=FIRM_A_ID, name="Shared Name"),
                ClientWorkspace(id=uuid4(), firm_id=FIRM_B_ID, name="Shared Name"),
            ]
        )


def test_timestamps_are_timezone_aware_and_updated_at_changes(
    tenant_data,
    owner_engine: Engine,
) -> None:
    with Session(owner_engine) as session, session.begin():
        user = session.get(User, ALICE_ID)
        assert user is not None
        original_updated_at = user.updated_at
        assert user.created_at.tzinfo is not None
        assert user.created_at.utcoffset() == timedelta(0)
        assert original_updated_at.tzinfo is not None
        user.display_name = "Alice Updated"
        session.flush()
        session.refresh(user)
        changed_updated_at = user.updated_at

    assert changed_updated_at > original_updated_at


@pytest.mark.parametrize(
    ("table", "identifier"),
    [
        (Firm, FIRM_A_ID),
        (User, ALICE_ID),
        (FirmMembership, ALICE_MEMBERSHIP_ID),
        (ClientWorkspace, APOLLO_FINANCE_ID),
    ],
)
def test_critical_parent_deletion_is_restricted(
    tenant_data,
    owner_engine: Engine,
    table,
    identifier,
) -> None:
    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        record = session.get(table, identifier)
        assert record is not None
        session.delete(record)
        session.flush()


def test_database_declares_expected_composite_constraints() -> None:
    grant_foreign_keys = {
        tuple(constraint.column_keys)
        for constraint in ClientAccessGrant.__table__.foreign_key_constraints
    }
    grant_unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in ClientAccessGrant.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert grant_foreign_keys == {
        ("firm_id", "membership_id"),
        ("firm_id", "client_id"),
    }
    assert ("firm_id", "membership_id", "client_id") in grant_unique_constraints


def test_runtime_role_cannot_self_assign_an_unassigned_client(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    with (
        pytest.raises(DBAPIError) as error,
        Session(app_engine) as session,
        session.begin(),
    ):
        apply_requested_client_scope(
            session,
            firm_context=FirmContext(
                user_id=ALICE_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
                firm_id=FIRM_A_ID,
                role=FirmRole.CONSULTANT,
            ),
            client_id=MERIDIAN_RETAIL_ID,
        )
        session.add(
            ClientAccessGrant(
                id=uuid4(),
                firm_id=FIRM_A_ID,
                client_id=MERIDIAN_RETAIL_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
            )
        )
        session.flush()

    assert getattr(error.value.orig, "sqlstate", None) == "42501"
    with Session(owner_engine) as session:
        grant_count = session.scalar(
            select(func.count())
            .select_from(ClientAccessGrant)
            .where(
                ClientAccessGrant.membership_id == ALICE_MEMBERSHIP_ID,
                ClientAccessGrant.client_id == MERIDIAN_RETAIL_ID,
            )
        )

    assert grant_count == 0
