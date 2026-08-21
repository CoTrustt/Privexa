from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from fixtures.tenant_foundation import (
    ACME_HEALTHCARE_ID,
    ALICE_APOLLO_GRANT_ID,
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    CAROL_MEMBERSHIP_ID,
    DAVID_ID,
    DAVID_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
    RAHUL_ID,
    RAHUL_MEMBERSHIP_ID,
)
from sqlalchemy import Engine, create_engine, delete, func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.clients.models import ClientWorkspace
from privexa_api.db.errors import RuntimeDatabaseSecurityError
from privexa_api.db.session import validate_runtime_database_security
from privexa_api.identity.models import Firm, User

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

PROTECTED_TABLES = {
    "firms",
    "users",
    "firm_memberships",
    "client_workspaces",
    "client_access_grants",
}

EXPECTED_POLICIES = {
    ("firms", "firms_scoped_select", "SELECT"),
    ("firms", "firms_scoped_update", "UPDATE"),
    ("users", "users_firm_scoped_select", "SELECT"),
    ("users", "users_self_update", "UPDATE"),
    (
        "firm_memberships",
        "firm_memberships_firm_scoped_select",
        "SELECT",
    ),
    ("client_workspaces", "client_workspaces_scoped_select", "SELECT"),
    ("client_workspaces", "client_workspaces_scoped_insert", "INSERT"),
    ("client_workspaces", "client_workspaces_scoped_update", "UPDATE"),
    (
        "client_access_grants",
        "client_access_grants_scoped_select",
        "SELECT",
    ),
}


def _principal(
    *,
    user_id: UUID,
    membership_id: UUID,
    firm_id: UUID,
    role: FirmRole,
) -> AuthenticatedPrincipal:
    from privexa_api.access_control.context import FirmContext

    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=user_id,
            membership_id=membership_id,
            firm_id=firm_id,
            role=role,
        ),
        stytch_member_id=f"member-{user_id}",
        stytch_organization_id=f"organization-{firm_id}",
        stytch_member_session_id=f"session-{membership_id}",
    )


ALICE = _principal(
    user_id=ALICE_ID,
    membership_id=ALICE_MEMBERSHIP_ID,
    firm_id=FIRM_A_ID,
    role=FirmRole.CONSULTANT,
)
DAVID = _principal(
    user_id=DAVID_ID,
    membership_id=DAVID_MEMBERSHIP_ID,
    firm_id=FIRM_A_ID,
    role=FirmRole.FIRM_ADMIN,
)
RAHUL = _principal(
    user_id=RAHUL_ID,
    membership_id=RAHUL_MEMBERSHIP_ID,
    firm_id=FIRM_A_ID,
    role=FirmRole.CONSULTANT,
)
BOB = _principal(
    user_id=BOB_ID,
    membership_id=BOB_MEMBERSHIP_ID,
    firm_id=FIRM_B_ID,
    role=FirmRole.CONSULTANT,
)


def _authorize_firm(session: Session, principal: AuthenticatedPrincipal) -> None:
    AccessControlService.authorize_firm(
        session,
        principal=principal,
        permission=Permission.FIRM_READ,
    )


def _authorize_client(
    session: Session,
    principal: AuthenticatedPrincipal,
    client_id: UUID,
    *,
    permission: Permission = Permission.CLIENT_READ,
) -> None:
    AccessControlService.authorize_client(
        session,
        principal=principal,
        client_id=client_id,
        permission=permission,
    )


def _assert_rls_violation(error: pytest.ExceptionInfo[DBAPIError]) -> None:
    assert getattr(error.value.orig, "sqlstate", None) == "42501"


def test_actual_database_has_complete_forced_rls_and_policy_inventory(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        table_rows = connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "pg_get_userbyid(c.relowner) AS owner_name "
                "FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
            ),
            {"tables": sorted(PROTECTED_TABLES)},
        ).all()
        policies = connection.execute(
            text(
                "SELECT tablename, policyname, cmd FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = ANY(:tables)"
            ),
            {"tables": sorted(PROTECTED_TABLES)},
        ).all()

    assert {row.relname for row in table_rows} == PROTECTED_TABLES
    assert all(row.relrowsecurity and row.relforcerowsecurity for row in table_rows)
    assert {(row.tablename, row.policyname, row.cmd) for row in policies} == EXPECTED_POLICIES


def test_runtime_role_is_non_owner_non_superuser_without_bypass_or_admin_grants(
    app_engine: Engine,
) -> None:
    with app_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, "
                "rolreplication FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        owners = (
            connection.execute(
                text(
                    "SELECT DISTINCT pg_get_userbyid(c.relowner) AS owner_name "
                    "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
                ),
                {"tables": sorted(PROTECTED_TABLES)},
            )
            .scalars()
            .all()
        )
        grants = connection.execute(
            text(
                "SELECT table_name, privilege_type, is_grantable "
                "FROM information_schema.role_table_grants "
                "WHERE grantee = current_user AND table_schema = 'public' "
                "AND table_name = ANY(:tables)"
            ),
            {"tables": sorted(PROTECTED_TABLES)},
        ).all()
        forbidden = connection.execute(
            text(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE') AS schema_create, "
                "bool_or(has_table_privilege(current_user, 'public.' || table_name, 'TRUNCATE')) "
                "AS can_truncate, "
                "bool_or(has_table_privilege(current_user, 'public.' || table_name, 'TRIGGER')) "
                "AS can_trigger "
                "FROM unnest(CAST(:tables AS text[])) AS table_name"
            ),
            {"tables": sorted(PROTECTED_TABLES)},
        ).one()

    assert role.rolname not in set(owners)
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    assert role.rolcreatedb is False
    assert role.rolcreaterole is False
    assert role.rolreplication is False
    actual_grants: dict[str, set[str]] = {table: set() for table in PROTECTED_TABLES}
    for row in grants:
        actual_grants[row.table_name].add(row.privilege_type)
    assert actual_grants == {
        "firms": {"SELECT", "UPDATE"},
        "users": {"SELECT", "UPDATE"},
        "firm_memberships": {"SELECT"},
        "client_workspaces": {"SELECT", "INSERT", "UPDATE"},
        "client_access_grants": {"SELECT"},
    }
    assert all(row.is_grantable == "NO" for row in grants)
    assert forbidden.schema_create is False
    assert forbidden.can_truncate is False
    assert forbidden.can_trigger is False


def test_private_helper_functions_have_hardened_search_path_and_grants(
    app_engine: Engine,
) -> None:
    with app_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT p.proname, p.prosecdef, p.proconfig, "
                "has_function_privilege(current_user, p.oid, 'EXECUTE') AS app_execute, "
                "has_function_privilege('public', p.oid, 'EXECUTE') AS public_execute "
                "FROM pg_proc AS p JOIN pg_namespace AS n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'privexa_private' ORDER BY p.proname"
            )
        ).all()

    assert {row.proname for row in rows} == {
        "current_context_uuid",
        "resolve_authenticated_identity",
        "resolve_current_membership",
        "validated_client_id",
        "validated_firm_id",
        "validated_role",
    }
    assert all(row.proconfig == ["search_path=pg_catalog"] for row in rows)
    assert all(row.app_execute for row in rows)
    assert all(not row.public_execute for row in rows)
    assert {row.proname for row in rows if row.prosecdef} == {
        "resolve_authenticated_identity",
        "resolve_current_membership",
        "validated_client_id",
        "validated_firm_id",
        "validated_role",
    }


def test_startup_security_validation_rejects_privileged_owner_role(
    owner_engine: Engine,
) -> None:
    with pytest.raises(RuntimeDatabaseSecurityError):
        validate_runtime_database_security(owner_engine)


def test_firm_scope_returns_only_the_authorized_firm_users_and_memberships(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        _authorize_firm(session, ALICE)
        firms = set(session.scalars(select(Firm.id)))
        users = set(session.scalars(select(User.id)))
        memberships = set(session.scalars(select(FirmMembership.id)))
        client_count = session.scalar(select(func.count()).select_from(ClientWorkspace))

    assert firms == {FIRM_A_ID}
    assert ALICE_ID in users
    assert BOB_ID not in users
    assert ALICE_MEMBERSHIP_ID in memberships
    assert BOB_MEMBERSHIP_ID not in memberships
    assert client_count == 0


def test_authorized_firm_update_and_self_profile_update_succeed_only_for_target_scope(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        AccessControlService.authorize_firm(
            session,
            principal=DAVID,
            permission=Permission.FIRM_UPDATE,
        )
        own_firm = session.execute(
            update(Firm).where(Firm.id == FIRM_A_ID).values(name="Firm A Updated")
        ).rowcount
        foreign_firm = session.execute(
            update(Firm).where(Firm.id == FIRM_B_ID).values(name="Firm B Compromised")
        ).rowcount

    with Session(app_engine) as session, session.begin():
        AccessControlService.authorize_self(
            session,
            principal=ALICE,
            permission=Permission.PROFILE_UPDATE_SELF,
        )
        own_user = session.execute(
            update(User).where(User.id == ALICE_ID).values(display_name="Alice Updated Safely")
        ).rowcount
        foreign_user = session.execute(
            update(User).where(User.id == BOB_ID).values(display_name="Bob Compromised")
        ).rowcount

    with Session(owner_engine) as owner_session:
        assert owner_session.get(Firm, FIRM_A_ID).name == "Firm A Updated"
        assert owner_session.get(Firm, FIRM_B_ID).name == "Northstar Privacy Advisors"
        assert owner_session.get(User, ALICE_ID).display_name == "Alice Updated Safely"
        assert owner_session.get(User, BOB_ID).display_name == "Consultant Bob"
    assert (own_firm, foreign_firm, own_user, foreign_user) == (1, 0, 1, 0)


@pytest.mark.parametrize(
    "statement, parameters",
    [
        (
            "INSERT INTO firms (id, name, status) VALUES (:id, 'Forbidden Firm', 'ACTIVE')",
            {},
        ),
        (
            "INSERT INTO users (id, email, display_name, status) "
            "VALUES (:id, :email, 'Forbidden User', 'ACTIVE')",
            {"email": "forbidden-user@example.test"},
        ),
        (
            "INSERT INTO firm_memberships (id, firm_id, user_id, role, status) "
            "VALUES (:id, :firm_id, :user_id, 'CONSULTANT', 'ACTIVE')",
            {"firm_id": FIRM_A_ID, "user_id": BOB_ID},
        ),
        (
            "INSERT INTO client_access_grants "
            "(id, firm_id, client_id, membership_id, status) "
            "VALUES (:id, :firm_id, :client_id, :membership_id, 'ACTIVE')",
            {
                "firm_id": FIRM_A_ID,
                "client_id": ACME_HEALTHCARE_ID,
                "membership_id": CAROL_MEMBERSHIP_ID,
            },
        ),
    ],
    ids=["firms", "users", "firm_memberships", "client_access_grants"],
)
def test_valid_firm_context_does_not_unlock_system_managed_inserts(
    tenant_data,
    app_engine: Engine,
    statement: str,
    parameters: dict[str, object],
) -> None:
    with (
        Session(app_engine) as session,
        pytest.raises(DBAPIError) as error,
        session.begin(),
    ):
        AccessControlService.authorize_firm(
            session,
            principal=DAVID,
            permission=Permission.FIRM_MEMBERS_MANAGE,
        )
        session.execute(text(statement), {"id": uuid4(), **parameters})
    _assert_rls_violation(error)


@pytest.mark.parametrize(
    "statement",
    [
        update(FirmMembership)
        .where(FirmMembership.id == ALICE_MEMBERSHIP_ID)
        .values(role=FirmRole.REVIEWER),
        delete(FirmMembership).where(FirmMembership.id == ALICE_MEMBERSHIP_ID),
        delete(Firm).where(Firm.id == FIRM_A_ID),
        delete(Firm).where(Firm.id == FIRM_B_ID),
    ],
)
def test_valid_firm_scope_cannot_use_unimplemented_mutations(
    tenant_data,
    app_engine: Engine,
    statement,
) -> None:
    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        AccessControlService.authorize_firm(
            session,
            principal=DAVID,
            permission=Permission.FIRM_MEMBERS_MANAGE,
        )
        session.execute(statement)
    _assert_rls_violation(error)


def test_rls_still_isolates_when_application_forgets_every_tenant_filter(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        _authorize_client(session, ALICE, APOLLO_FINANCE_ID)
        client_ids = list(session.scalars(select(ClientWorkspace.id)))
        grant_ids = list(session.scalars(select(ClientAccessGrant.id)))

    assert client_ids == [APOLLO_FINANCE_ID]
    assert grant_ids == [ALICE_APOLLO_GRANT_ID]


def test_same_firm_other_client_grant_is_invisible_by_known_primary_key(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        _authorize_client(session, ALICE, APOLLO_FINANCE_ID)
        other_client_grant = session.get(ClientAccessGrant, tenant_data.alice_acme_grant.id)
        cross_firm_grant = session.get(ClientAccessGrant, tenant_data.bob_northstar_grant.id)

    assert other_client_grant is None
    assert cross_firm_grant is None


def test_known_cross_client_and_cross_firm_ids_remain_invisible_to_orm(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        _authorize_client(session, ALICE, APOLLO_FINANCE_ID)
        beta_direct = session.get(ClientWorkspace, MERIDIAN_RETAIL_ID)
        gamma_direct = session.get(ClientWorkspace, NORTHSTAR_RETAIL_ID)
        beta_explicit = session.scalar(
            select(ClientWorkspace).where(ClientWorkspace.id == MERIDIAN_RETAIL_ID)
        )
        gamma_explicit = session.scalar(
            select(ClientWorkspace).where(ClientWorkspace.id == NORTHSTAR_RETAIL_ID)
        )
        beta_exists = session.scalar(
            select(
                select(ClientWorkspace.id).where(ClientWorkspace.id == MERIDIAN_RETAIL_ID).exists()
            )
        )

    assert beta_direct is None
    assert gamma_direct is None
    assert beta_explicit is None
    assert gamma_explicit is None
    assert beta_exists is False


def test_raw_sql_and_aggregate_queries_are_tenant_isolated(
    tenant_data,
    app_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        _authorize_client(session, ALICE, APOLLO_FINANCE_ID)
        rows = session.execute(text("SELECT id, firm_id FROM client_workspaces")).all()
        beta = session.execute(
            text("SELECT id FROM client_workspaces WHERE id = :id"),
            {"id": MERIDIAN_RETAIL_ID},
        ).all()
        gamma = session.execute(
            text("SELECT id FROM client_workspaces WHERE id = :id"),
            {"id": NORTHSTAR_RETAIL_ID},
        ).all()
        count = session.scalar(text("SELECT count(*) FROM client_workspaces"))

    assert rows == [(APOLLO_FINANCE_ID, FIRM_A_ID)]
    assert beta == []
    assert gamma == []
    assert count == 1


def test_join_of_two_protected_tables_is_independently_isolated(
    tenant_data,
    app_engine: Engine,
) -> None:
    statement = select(ClientWorkspace.id, ClientAccessGrant.id).join(
        ClientAccessGrant,
        (ClientAccessGrant.firm_id == ClientWorkspace.firm_id)
        & (ClientAccessGrant.client_id == ClientWorkspace.id),
    )
    with Session(app_engine) as session, session.begin():
        _authorize_client(session, ALICE, APOLLO_FINANCE_ID)
        rows = session.execute(statement).all()

    assert rows == [(APOLLO_FINANCE_ID, ALICE_APOLLO_GRANT_ID)]


@pytest.mark.parametrize("table_name", sorted(PROTECTED_TABLES))
def test_missing_context_select_fails_closed_for_every_protected_table(
    tenant_data,
    app_engine: Engine,
    table_name: str,
) -> None:
    with Session(app_engine) as session, session.begin():
        count = session.scalar(text(f"SELECT count(*) FROM {table_name}"))

    assert count == 0


@pytest.mark.parametrize(
    "statement, parameters",
    [
        (
            "INSERT INTO firms (id, name, status) VALUES (:id, 'Malicious Firm', 'ACTIVE')",
            {},
        ),
        (
            "INSERT INTO users (id, email, display_name, status) "
            "VALUES (:id, :email, 'Malicious User', 'ACTIVE')",
            {"email": "malicious-user@example.test"},
        ),
        (
            "INSERT INTO firm_memberships (id, firm_id, user_id, role, status) "
            "VALUES (:id, :firm_id, :user_id, 'CONSULTANT', 'ACTIVE')",
            {"firm_id": FIRM_A_ID, "user_id": BOB_ID},
        ),
        (
            "INSERT INTO client_workspaces (id, firm_id, name, status) "
            "VALUES (:id, :firm_id, 'Malicious Client', 'ACTIVE')",
            {"firm_id": FIRM_A_ID},
        ),
        (
            "INSERT INTO client_access_grants "
            "(id, firm_id, client_id, membership_id, status) "
            "VALUES (:id, :firm_id, :client_id, :membership_id, 'ACTIVE')",
            {
                "firm_id": FIRM_A_ID,
                "client_id": ACME_HEALTHCARE_ID,
                "membership_id": CAROL_MEMBERSHIP_ID,
            },
        ),
    ],
    ids=["firms", "users", "firm_memberships", "client_workspaces", "client_access_grants"],
)
def test_missing_context_insert_is_rejected_for_every_protected_table(
    tenant_data,
    app_engine: Engine,
    statement: str,
    parameters: dict[str, object],
) -> None:
    malicious_id = uuid4()
    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        session.execute(text(statement), {"id": malicious_id, **parameters})
    _assert_rls_violation(error)


@pytest.mark.parametrize(
    "table_name, identifier, assignment",
    [
        ("firms", FIRM_A_ID, "name = 'Changed'"),
        ("users", ALICE_ID, "display_name = 'Changed'"),
        ("client_workspaces", APOLLO_FINANCE_ID, "name = 'Changed'"),
    ],
)
def test_missing_context_update_mutates_no_rows_on_mutable_tables(
    tenant_data,
    app_engine: Engine,
    table_name: str,
    identifier: UUID,
    assignment: str,
) -> None:
    with Session(app_engine) as session, session.begin():
        updated = session.execute(
            text(f"UPDATE {table_name} SET {assignment} WHERE id = :id"),
            {"id": identifier},
        ).rowcount

    assert updated == 0


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE firm_memberships SET role = 'REVIEWER' WHERE id = :id",
        "UPDATE client_access_grants SET status = 'ACTIVE' WHERE id = :id",
        "DELETE FROM firms WHERE id = :id",
        "DELETE FROM users WHERE id = :id",
        "DELETE FROM firm_memberships WHERE id = :id",
        "DELETE FROM client_workspaces WHERE id = :id",
        "DELETE FROM client_access_grants WHERE id = :id",
    ],
)
def test_runtime_role_lacks_unimplemented_update_and_delete_privileges(
    tenant_data,
    app_engine: Engine,
    statement: str,
) -> None:
    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        session.execute(text(statement), {"id": ALICE_MEMBERSHIP_ID})
    _assert_rls_violation(error)


@pytest.mark.parametrize("invalid_value", ["not-a-uuid", str(uuid4())])
def test_malformed_and_nonexistent_database_context_fails_closed(
    tenant_data,
    app_engine: Engine,
    invalid_value: str,
) -> None:
    with Session(app_engine) as session, session.begin():
        for setting in ("user_id", "membership_id", "firm_id", "client_id"):
            session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": f"privexa.{setting}", "value": invalid_value},
            )
        visible = session.scalar(text("SELECT count(*) FROM client_workspaces"))

    assert visible == 0


def test_mismatched_firm_and_client_context_fails_closed(
    tenant_data,
    app_engine: Engine,
) -> None:
    settings = {
        "privexa.user_id": ALICE_ID,
        "privexa.membership_id": ALICE_MEMBERSHIP_ID,
        "privexa.firm_id": FIRM_A_ID,
        "privexa.client_id": NORTHSTAR_RETAIL_ID,
    }
    with Session(app_engine) as session, session.begin():
        for name, value in settings.items():
            session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": str(value)},
            )
        rows = session.execute(text("SELECT id FROM client_workspaces")).all()

    assert rows == []


def test_tenant_setting_values_are_bound_and_cannot_inject_sql(
    tenant_data,
    app_engine: Engine,
) -> None:
    payload = f"{FIRM_A_ID}'; DROP TABLE firms; --"
    with Session(app_engine) as session, session.begin():
        session.execute(
            text("SELECT set_config(:name, :value, true)"),
            {"name": "privexa.firm_id", "value": payload},
        )
        visible = session.scalar(text("SELECT count(*) FROM firms"))
        table_exists = session.scalar(text("SELECT to_regclass('public.firms') IS NOT NULL"))

    assert visible == 0
    assert table_exists is True


def test_valid_client_insert_succeeds_for_admin_candidate_scope(
    tenant_data,
    app_engine: Engine,
) -> None:
    new_client_id = uuid4()
    with Session(app_engine) as session, session.begin():
        authorization = AccessControlService.authorize_firm(
            session,
            principal=DAVID,
            permission=Permission.CLIENT_CREATE,
        )
        from privexa_api.db.tenant_scope import apply_requested_client_scope

        apply_requested_client_scope(
            session,
            firm_context=authorization.firm_context,
            client_id=new_client_id,
        )
        session.add(ClientWorkspace(id=new_client_id, firm_id=FIRM_A_ID, name="Valid Admin Client"))
        session.flush()
        session.expire_all()
        assert (
            session.scalar(select(ClientWorkspace.id).where(ClientWorkspace.id == new_client_id))
            == new_client_id
        )


@pytest.mark.parametrize(
    "claimed_firm_id, claimed_client_id",
    [
        (FIRM_A_ID, uuid4()),
        (FIRM_B_ID, uuid4()),
    ],
    ids=["cross-client", "cross-firm"],
)
def test_cross_tenant_client_insert_is_rejected_by_with_check(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
    claimed_firm_id: UUID,
    claimed_client_id: UUID,
) -> None:
    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        _authorize_client(
            session,
            DAVID,
            APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_UPDATE,
        )
        session.add(
            ClientWorkspace(
                id=claimed_client_id,
                firm_id=claimed_firm_id,
                name="Cross-tenant Insert",
            )
        )
        session.flush()
    _assert_rls_violation(error)

    with Session(owner_engine) as owner_session:
        assert owner_session.get(ClientWorkspace, claimed_client_id) is None


def test_same_tenant_update_succeeds_but_cross_tenant_updates_mutate_nothing(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    with Session(app_engine) as session, session.begin():
        _authorize_client(
            session,
            DAVID,
            APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_UPDATE,
        )
        allowed = session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == APOLLO_FINANCE_ID)
            .values(name="Apollo Safely Updated")
        ).rowcount
        beta = session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == MERIDIAN_RETAIL_ID)
            .values(name="Beta Compromised")
        ).rowcount
        gamma = session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == NORTHSTAR_RETAIL_ID)
            .values(name="Gamma Compromised")
        ).rowcount

    with Session(owner_engine) as owner_session:
        assert owner_session.get(ClientWorkspace, APOLLO_FINANCE_ID).name == (
            "Apollo Safely Updated"
        )
        assert owner_session.get(ClientWorkspace, MERIDIAN_RETAIL_ID).name == "Meridian Retail"
        assert owner_session.get(ClientWorkspace, NORTHSTAR_RETAIL_ID).name == "Northstar Retail"
    assert (allowed, beta, gamma) == (1, 0, 0)


@pytest.mark.parametrize(
    "ownership_change",
    [
        {"id": uuid4()},
        {"firm_id": FIRM_B_ID},
    ],
    ids=["client-id", "firm-id"],
)
def test_tenant_ownership_cannot_be_reassigned(
    tenant_data,
    app_engine: Engine,
    ownership_change: dict[str, UUID],
) -> None:
    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        _authorize_client(
            session,
            DAVID,
            APOLLO_FINANCE_ID,
            permission=Permission.CLIENT_UPDATE,
        )
        session.execute(
            update(ClientWorkspace)
            .where(ClientWorkspace.id == APOLLO_FINANCE_ID)
            .values(**ownership_change)
        )
    _assert_rls_violation(error)


def test_hard_delete_is_default_denied_even_in_same_client_scope(
    tenant_data,
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    for identifier in (APOLLO_FINANCE_ID, MERIDIAN_RETAIL_ID, NORTHSTAR_RETAIL_ID):
        with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
            _authorize_client(
                session,
                DAVID,
                APOLLO_FINANCE_ID,
                permission=Permission.CLIENT_ARCHIVE,
            )
            session.execute(delete(ClientWorkspace).where(ClientWorkspace.id == identifier))
        _assert_rls_violation(error)

    with Session(owner_engine) as owner_session:
        assert owner_session.get(ClientWorkspace, APOLLO_FINANCE_ID) is not None
        assert owner_session.get(ClientWorkspace, MERIDIAN_RETAIL_ID) is not None
        assert owner_session.get(ClientWorkspace, NORTHSTAR_RETAIL_ID) is not None


def test_client_access_grants_are_immutable_through_runtime_role(
    tenant_data,
    app_engine: Engine,
) -> None:
    statements = (
        update(ClientAccessGrant)
        .where(ClientAccessGrant.id == ALICE_APOLLO_GRANT_ID)
        .values(status="ACTIVE"),
        delete(ClientAccessGrant).where(ClientAccessGrant.id == ALICE_APOLLO_GRANT_ID),
    )
    for statement in statements:
        with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
            _authorize_client(session, ALICE, APOLLO_FINANCE_ID)
            session.execute(statement)
        _assert_rls_violation(error)


def test_composite_foreign_keys_reject_cross_firm_relationship_even_for_owner(
    tenant_data,
    owner_engine: Engine,
) -> None:
    from sqlalchemy.exc import IntegrityError

    with Session(owner_engine) as session, pytest.raises(IntegrityError), session.begin():
        session.add(
            ClientAccessGrant(
                id=uuid4(),
                firm_id=FIRM_A_ID,
                client_id=NORTHSTAR_RETAIL_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
            )
        )
        session.flush()


def _single_connection_engine(app_database_url: str) -> Engine:
    return create_engine(
        app_database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )


def _assert_context_is_empty(session: Session) -> None:
    row = session.execute(
        text(
            "SELECT "
            "NULLIF(current_setting('privexa.user_id', true), '') AS user_id, "
            "NULLIF(current_setting('privexa.membership_id', true), '') AS membership_id, "
            "NULLIF(current_setting('privexa.firm_id', true), '') AS firm_id, "
            "NULLIF(current_setting('privexa.client_id', true), '') AS client_id"
        )
    ).one()
    assert tuple(row) == (None, None, None, None)


def test_transaction_local_context_does_not_leak_through_pool_after_commit(
    tenant_data,
    app_database_url: str,
) -> None:
    engine = _single_connection_engine(app_database_url)
    try:
        with Session(engine) as alpha, alpha.begin():
            _authorize_client(alpha, ALICE, APOLLO_FINANCE_ID)
            first_pid = alpha.scalar(text("SELECT pg_backend_pid()"))
            assert set(alpha.scalars(select(ClientWorkspace.id))) == {APOLLO_FINANCE_ID}

        with Session(engine) as unscoped, unscoped.begin():
            second_pid = unscoped.scalar(text("SELECT pg_backend_pid()"))
            _assert_context_is_empty(unscoped)
            assert unscoped.scalar(select(func.count()).select_from(ClientWorkspace)) == 0

        with Session(engine) as gamma, gamma.begin():
            third_pid = gamma.scalar(text("SELECT pg_backend_pid()"))
            _authorize_client(gamma, BOB, NORTHSTAR_RETAIL_ID)
            assert set(gamma.scalars(select(ClientWorkspace.id))) == {NORTHSTAR_RETAIL_ID}

        assert first_pid == second_pid == third_pid
    finally:
        engine.dispose()


def test_transaction_local_context_does_not_leak_after_rollback_or_exception(
    tenant_data,
    app_database_url: str,
) -> None:
    engine = _single_connection_engine(app_database_url)
    try:
        first_pid = None
        with pytest.raises(RuntimeError), Session(engine) as alpha, alpha.begin():
            _authorize_client(alpha, ALICE, APOLLO_FINANCE_ID)
            first_pid = alpha.scalar(text("SELECT pg_backend_pid()"))
            assert set(alpha.scalars(select(ClientWorkspace.id))) == {APOLLO_FINANCE_ID}
            raise RuntimeError("deterministic request failure")

        with Session(engine) as gamma, gamma.begin():
            second_pid = gamma.scalar(text("SELECT pg_backend_pid()"))
            _assert_context_is_empty(gamma)
            _authorize_client(gamma, BOB, NORTHSTAR_RETAIL_ID)
            assert set(gamma.scalars(select(ClientWorkspace.id))) == {NORTHSTAR_RETAIL_ID}

        assert first_pid == second_pid
    finally:
        engine.dispose()


def test_concurrent_tenant_transactions_have_no_context_bleed(
    tenant_data,
    app_database_url: str,
) -> None:
    engine = create_engine(
        app_database_url,
        pool_pre_ping=True,
        pool_size=3,
        max_overflow=0,
    )
    barrier = Barrier(3)
    cases = (
        (ALICE, APOLLO_FINANCE_ID),
        (RAHUL, ACME_HEALTHCARE_ID),
        (BOB, NORTHSTAR_RETAIL_ID),
    )

    def read_repeatedly(case: tuple[AuthenticatedPrincipal, UUID]) -> list[set[UUID]]:
        principal, client_id = case
        with Session(engine) as session, session.begin():
            _authorize_client(session, principal, client_id)
            barrier.wait()
            return [set(session.scalars(select(ClientWorkspace.id))) for _ in range(10)]

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(read_repeatedly, cases))
    finally:
        engine.dispose()

    for result, (_, expected_client_id) in zip(results, cases, strict=True):
        assert result == [{expected_client_id}] * 10


def test_firm_admin_all_client_access_remains_bounded_to_own_firm(
    tenant_data,
    app_engine: Engine,
) -> None:
    for client_id in (APOLLO_FINANCE_ID, MERIDIAN_RETAIL_ID):
        with Session(app_engine) as session, session.begin():
            _authorize_client(session, DAVID, client_id)
            assert set(session.scalars(select(ClientWorkspace.id))) == {client_id}

    with Session(app_engine) as session, session.begin():
        from privexa_api.access_control.errors import AuthorizationResourceNotFoundError

        with pytest.raises(AuthorizationResourceNotFoundError):
            _authorize_client(session, DAVID, NORTHSTAR_RETAIL_ID)


def test_direct_valid_guc_tampering_documents_server_credential_trust_boundary(
    tenant_data,
    app_engine: Engine,
) -> None:
    settings = {
        "privexa.user_id": BOB_ID,
        "privexa.membership_id": BOB_MEMBERSHIP_ID,
        "privexa.firm_id": FIRM_B_ID,
        "privexa.client_id": NORTHSTAR_RETAIL_ID,
    }
    with Session(app_engine) as session, session.begin():
        for name, value in settings.items():
            session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": name, "value": str(value)},
            )
        visible = set(session.scalars(select(ClientWorkspace.id)))

    # Custom GUCs are not authorization tokens. The trusted server owns this credential and must
    # establish them only after PBI-0.3 authorization; an HTTP caller never receives this surface.
    assert visible == {NORTHSTAR_RETAIL_ID}
