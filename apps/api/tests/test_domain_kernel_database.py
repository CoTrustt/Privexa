from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fixtures.domain_kernel import ProfessionalRecordProbe, record_probe
from fixtures.tenant_foundation import (
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_MEMBERSHIP_ID,
    DAVID_ID,
    DAVID_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.domain.events import DomainEvent, DomainEventCollector

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

TABLE_NAME = ProfessionalRecordProbe.__tablename__
APOLLO_RECORD_ID = UUID("00000000-0000-4000-8000-000000001201")
MERIDIAN_RECORD_ID = UUID("00000000-0000-4000-8000-000000001202")
NORTHSTAR_RECORD_ID = UUID("00000000-0000-4000-8000-000000001203")


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=DAVID_ID,
            membership_id=DAVID_MEMBERSHIP_ID,
            firm_id=FIRM_A_ID,
            role=FirmRole.FIRM_ADMIN,
        ),
        stytch_member_id="member-domain-kernel-david",
        stytch_organization_id="organization-domain-kernel-firm-a",
        stytch_member_session_id="session-domain-kernel-david",
    )


def _authorize_apollo(session: Session, permission: Permission = Permission.CLIENT_UPDATE) -> None:
    _authorize_workspace(session, APOLLO_FINANCE_ID, permission)


def _authorize_workspace(
    session: Session,
    client_id: UUID,
    permission: Permission = Permission.CLIENT_UPDATE,
) -> None:
    AccessControlService.authorize_client(
        session,
        principal=_principal(),
        client_id=client_id,
        permission=permission,
    )


@pytest.fixture
def professional_record_table(tenant_data, owner_engine: Engine, app_engine: Engine):
    runtime_role = app_engine.url.username
    if runtime_role is None or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", runtime_role):
        raise RuntimeError("Unsafe test runtime role")
    quoted_role = owner_engine.dialect.identifier_preparer.quote(runtime_role)

    with owner_engine.begin() as connection:
        connection.execute(text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))
        ProfessionalRecordProbe.__table__.create(connection)
        connection.execute(text(f"ALTER TABLE {TABLE_NAME} ENABLE ROW LEVEL SECURITY"))
        connection.execute(text(f"ALTER TABLE {TABLE_NAME} FORCE ROW LEVEL SECURITY"))
        connection.execute(
            text(
                f"CREATE POLICY {TABLE_NAME}_scoped_select ON {TABLE_NAME} FOR SELECT USING ("
                "firm_id = privexa_private.validated_firm_id() AND "
                "client_id = privexa_private.validated_client_id())"
            )
        )
        connection.execute(
            text(
                f"CREATE POLICY {TABLE_NAME}_scoped_insert ON {TABLE_NAME} FOR INSERT WITH CHECK ("
                "firm_id = privexa_private.validated_firm_id() AND "
                "client_id = privexa_private.validated_client_id() AND "
                "created_by_membership_id = privexa_private.current_context_uuid("
                "'privexa.membership_id') AND "
                "updated_by_membership_id = privexa_private.current_context_uuid("
                "'privexa.membership_id'))"
            )
        )
        connection.execute(
            text(
                f"CREATE POLICY {TABLE_NAME}_scoped_update ON {TABLE_NAME} FOR UPDATE USING ("
                "firm_id = privexa_private.validated_firm_id() AND "
                "client_id = privexa_private.validated_client_id()) WITH CHECK ("
                "firm_id = privexa_private.validated_firm_id() AND "
                "client_id = privexa_private.validated_client_id() AND "
                "updated_by_membership_id = privexa_private.current_context_uuid("
                "'privexa.membership_id'))"
            )
        )
        connection.execute(text(f"REVOKE ALL PRIVILEGES ON {TABLE_NAME} FROM {quoted_role}"))
        connection.execute(text(f"GRANT SELECT, INSERT ON {TABLE_NAME} TO {quoted_role}"))
        connection.execute(
            text(
                "GRANT UPDATE (title, updated_by_membership_id, archived_at, "
                f"archived_by_membership_id, updated_at, version) ON {TABLE_NAME} TO {quoted_role}"
            )
        )

    try:
        yield
    finally:
        with owner_engine.begin() as connection:
            connection.execute(text(f"REVOKE ALL PRIVILEGES ON {TABLE_NAME} FROM {quoted_role}"))
            connection.execute(text(f"DROP TABLE IF EXISTS {TABLE_NAME}"))


def _seed_records(owner_engine: Engine) -> None:
    with Session(owner_engine) as session, session.begin():
        session.add_all(
            [
                record_probe(
                    record_id=APOLLO_RECORD_ID,
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                    title="Apollo",
                ),
                record_probe(
                    record_id=MERIDIAN_RECORD_ID,
                    firm_id=FIRM_A_ID,
                    client_id=MERIDIAN_RETAIL_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                    title="Meridian",
                ),
                record_probe(
                    record_id=NORTHSTAR_RECORD_ID,
                    firm_id=FIRM_B_ID,
                    client_id=NORTHSTAR_RETAIL_ID,
                    membership_id=BOB_MEMBERSHIP_ID,
                    title="Northstar",
                ),
            ]
        )


def test_representative_table_has_forced_rls_policies_indexes_and_bounded_grants(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    inspector = inspect(owner_engine)
    indexes = {item["name"]: item for item in inspector.get_indexes(TABLE_NAME)}
    checks = {item["name"] for item in inspector.get_check_constraints(TABLE_NAME)}
    foreign_keys = {item["name"] for item in inspector.get_foreign_keys(TABLE_NAME)}

    with owner_engine.connect() as connection:
        table = connection.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                "pg_get_userbyid(c.relowner) AS owner_name "
                "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = :table_name"
            ),
            {"table_name": TABLE_NAME},
        ).one()
        policies = connection.execute(
            text(
                "SELECT policyname, cmd, qual, with_check FROM pg_policies "
                "WHERE schemaname = current_schema() AND tablename = :table_name"
            ),
            {"table_name": TABLE_NAME},
        ).all()

    with app_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        table_grants = set(
            connection.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = current_user AND table_schema = current_schema() "
                    "AND table_name = :table_name"
                ),
                {"table_name": TABLE_NAME},
            ).scalars()
        )
        update_columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.role_column_grants "
                    "WHERE grantee = current_user AND table_schema = current_schema() "
                    "AND table_name = :table_name AND privilege_type = 'UPDATE'"
                ),
                {"table_name": TABLE_NAME},
            ).scalars()
        )

    assert table.relrowsecurity is True
    assert table.relforcerowsecurity is True
    assert table.owner_name != role.rolname
    assert role.rolsuper is False
    assert role.rolbypassrls is False
    assert {(row.policyname, row.cmd) for row in policies} == {
        (f"{TABLE_NAME}_scoped_select", "SELECT"),
        (f"{TABLE_NAME}_scoped_insert", "INSERT"),
        (f"{TABLE_NAME}_scoped_update", "UPDATE"),
    }
    policy_sql = " ".join(f"{row.qual or ''} {row.with_check or ''}" for row in policies)
    for required in (
        "validated_firm_id",
        "validated_client_id",
        "privexa.membership_id",
    ):
        assert required in policy_sql
    assert table_grants == {"SELECT", "INSERT"}
    assert update_columns == {
        "title",
        "updated_by_membership_id",
        "archived_at",
        "archived_by_membership_id",
        "updated_at",
        "version",
    }
    assert f"ix_{TABLE_NAME}_firm_client_created" in indexes
    assert f"ix_{TABLE_NAME}_firm_client_archived" in indexes
    assert any(name and name.endswith("version_positive") for name in checks)
    assert any(name and name.endswith("archive_provenance_complete") for name in checks)
    assert {
        f"fk_{TABLE_NAME}_firm_client",
        f"fk_{TABLE_NAME}_firm_creator_membership",
        f"fk_{TABLE_NAME}_firm_updater_membership",
        f"fk_{TABLE_NAME}_firm_archiver_membership",
    } <= foreign_keys


def test_database_rejects_cross_firm_workspace_and_actor_ownership(
    professional_record_table,
    owner_engine: Engine,
) -> None:
    bad_client = record_probe(
        record_id=UUID("00000000-0000-4000-8000-000000001211"),
        firm_id=FIRM_A_ID,
        client_id=NORTHSTAR_RETAIL_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
    )
    with Session(owner_engine) as session, session.begin(), pytest.raises(IntegrityError):
        session.add(bad_client)
        session.flush()

    bad_actor = record_probe(
        record_id=UUID("00000000-0000-4000-8000-000000001212"),
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=BOB_MEMBERSHIP_ID,
    )
    with Session(owner_engine) as session, session.begin(), pytest.raises(IntegrityError):
        session.add(bad_actor)
        session.flush()


def test_unfiltered_runtime_query_only_returns_the_authorized_workspace(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed_records(owner_engine)

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session, Permission.CLIENT_READ)
        visible = set(session.scalars(select(ProfessionalRecordProbe.id)))
        same_firm_other_workspace = session.get(ProfessionalRecordProbe, MERIDIAN_RECORD_ID)
        other_firm = session.get(ProfessionalRecordProbe, NORTHSTAR_RECORD_ID)

    assert visible == {APOLLO_RECORD_ID}
    assert same_firm_other_workspace is None
    assert other_firm is None

    with Session(app_engine) as session, session.begin():
        assert list(session.scalars(select(ProfessionalRecordProbe.id))) == []


def test_raw_sql_respects_workspace_rls_and_missing_or_invalid_context_fails_closed(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed_records(owner_engine)

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session, Permission.CLIENT_UPDATE)
        visible = set(session.execute(text(f"SELECT id FROM {TABLE_NAME}")).scalars())
        foreign_update = session.execute(
            text(
                f"UPDATE {TABLE_NAME} SET title = 'forged', "
                "updated_by_membership_id = :actor WHERE id = :record_id"
            ),
            {"actor": DAVID_MEMBERSHIP_ID, "record_id": MERIDIAN_RECORD_ID},
        ).rowcount

    with Session(app_engine) as session, session.begin():
        missing_visible = session.scalar(text(f"SELECT count(*) FROM {TABLE_NAME}"))
        missing_update = session.execute(
            text(f"UPDATE {TABLE_NAME} SET title = 'unscoped' WHERE id = :record_id"),
            {"record_id": APOLLO_RECORD_ID},
        ).rowcount

    with Session(app_engine) as session, session.begin():
        for setting in ("user_id", "membership_id", "firm_id", "client_id"):
            session.execute(
                text("SELECT set_config(:name, :value, true)"),
                {"name": f"privexa.{setting}", "value": "not-a-uuid"},
            )
        invalid_visible = session.scalar(text(f"SELECT count(*) FROM {TABLE_NAME}"))

    assert visible == {APOLLO_RECORD_ID}
    assert foreign_update == 0
    assert missing_visible == 0
    assert missing_update == 0
    assert invalid_visible == 0


def test_authorized_runtime_insert_derives_a_valid_tenant_and_actor_record(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    record_id = UUID("00000000-0000-4000-8000-000000001214")
    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        session.add(
            record_probe(
                record_id=record_id,
                firm_id=FIRM_A_ID,
                client_id=APOLLO_FINANCE_ID,
                membership_id=DAVID_MEMBERSHIP_ID,
                title="Authorized creation",
            )
        )

    with Session(owner_engine) as session:
        record = session.get(ProfessionalRecordProbe, record_id)
        assert record is not None
        assert record.version == 1
        assert record.created_by_membership_id == DAVID_MEMBERSHIP_ID
        assert record.updated_by_membership_id == DAVID_MEMBERSHIP_ID
        assert record.created_at.tzinfo is not None
        assert record.updated_at.tzinfo is not None


def test_rls_rejects_forged_ownership_actor_and_hard_delete(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed_records(owner_engine)

    forged = record_probe(
        record_id=UUID("00000000-0000-4000-8000-000000001213"),
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=BOB_MEMBERSHIP_ID,
    )
    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        session.add(forged)
        with pytest.raises(DBAPIError):
            session.flush()

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    f"UPDATE {TABLE_NAME} SET updated_by_membership_id = :forged_actor "
                    "WHERE id = :record_id"
                ),
                {"forged_actor": ALICE_MEMBERSHIP_ID, "record_id": APOLLO_RECORD_ID},
            )

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        with pytest.raises(DBAPIError):
            session.execute(
                text(
                    f"UPDATE {TABLE_NAME} SET created_by_membership_id = :forged_actor "
                    "WHERE id = :record_id"
                ),
                {"forged_actor": DAVID_MEMBERSHIP_ID, "record_id": APOLLO_RECORD_ID},
            )

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        record = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert record is not None
        record.client_id = MERIDIAN_RETAIL_ID
        with pytest.raises(DBAPIError):
            session.flush()

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        record = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert record is not None
        session.delete(record)
        with pytest.raises(DBAPIError):
            session.flush()


def test_sqlalchemy_versioning_rejects_concurrent_stale_update(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed_records(owner_engine)
    first = Session(app_engine, expire_on_commit=False)
    second = Session(app_engine, expire_on_commit=False)
    try:
        _authorize_apollo(first)
        _authorize_apollo(second)
        first_record = first.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        second_record = second.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert first_record is not None and second_record is not None
        assert first_record.version == second_record.version == 1

        first_record.title = "First update"
        first_record.updated_by_membership_id = DAVID_MEMBERSHIP_ID
        first.commit()
        assert first_record.version == 2

        second_record.title = "Stale update"
        second_record.updated_by_membership_id = DAVID_MEMBERSHIP_ID
        with pytest.raises(StaleDataError):
            second.commit()
        second.rollback()

        _authorize_apollo(second)
        recovered = second.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert recovered is not None
        recovered.title = "Recovered update"
        recovered.updated_by_membership_id = DAVID_MEMBERSHIP_ID
        second.commit()
        assert recovered.version == 3
    finally:
        first.close()
        second.close()


def test_archival_is_attributed_and_does_not_enable_hard_deletion(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed_records(owner_engine)
    archived_at = datetime.now(UTC)

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        record = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert record is not None
        record.archived_at = archived_at
        record.archived_by_membership_id = DAVID_MEMBERSHIP_ID
        record.updated_by_membership_id = DAVID_MEMBERSHIP_ID

    with Session(owner_engine) as session:
        record = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert record is not None
        assert record.archived_at == archived_at
        assert record.archived_by_membership_id == DAVID_MEMBERSHIP_ID
        assert record.version == 2


def test_constraints_reject_invalid_versions_timestamps_and_null_ownership_then_recover(
    professional_record_table,
    owner_engine: Engine,
) -> None:
    with owner_engine.begin() as connection, pytest.raises(IntegrityError):
        connection.execute(
            text(
                f"INSERT INTO {TABLE_NAME} "
                "(id, firm_id, client_id, created_by_membership_id, "
                "updated_by_membership_id, version, title) "
                "VALUES (:id, :firm_id, :client_id, :actor, :actor, 0, 'invalid version')"
            ),
            {
                "id": UUID("00000000-0000-4000-8000-000000001220"),
                "firm_id": FIRM_A_ID,
                "client_id": APOLLO_FINANCE_ID,
                "actor": ALICE_MEMBERSHIP_ID,
            },
        )

    invalid_cases = (
        {"firm_id": None},
        {
            "created_at": datetime(2026, 8, 22, 11, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 22, 10, 0, tzinfo=UTC),
        },
    )
    for index, changes in enumerate(invalid_cases, start=1):
        invalid = record_probe(
            record_id=UUID(f"00000000-0000-4000-8000-{1220 + index:012d}"),
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            membership_id=ALICE_MEMBERSHIP_ID,
        )
        for name, value in changes.items():
            setattr(invalid, name, value)
        with Session(owner_engine) as session, session.begin(), pytest.raises(IntegrityError):
            session.add(invalid)
            session.flush()

    valid_id = UUID("00000000-0000-4000-8000-000000001229")
    with Session(owner_engine) as session, session.begin():
        session.add(
            record_probe(
                record_id=valid_id,
                firm_id=FIRM_A_ID,
                client_id=APOLLO_FINANCE_ID,
                membership_id=ALICE_MEMBERSHIP_ID,
            )
        )
    with Session(owner_engine) as session:
        assert session.get(ProfessionalRecordProbe, valid_id) is not None


def test_orm_updates_preserve_creation_time_advance_update_time_and_version(
    professional_record_table,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed_records(owner_engine)
    with Session(owner_engine) as session:
        original = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert original is not None
        original_created_at = original.created_at
        original_updated_at = original.updated_at

    with Session(app_engine) as session, session.begin():
        _authorize_apollo(session)
        record = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert record is not None
        record.title = "Timestamped update"
        record.updated_by_membership_id = DAVID_MEMBERSHIP_ID

    with Session(owner_engine) as session:
        updated = session.get(ProfessionalRecordProbe, APOLLO_RECORD_ID)
        assert updated is not None
        assert updated.created_at == original_created_at
        assert updated.updated_at >= original_updated_at
        assert updated.updated_at.tzinfo is not None
        assert updated.version == 2


def test_representative_record_context_does_not_leak_after_commit_or_rollback(
    professional_record_table,
    owner_engine: Engine,
    app_database_url: str,
) -> None:
    _seed_records(owner_engine)
    engine = create_engine(
        app_database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    try:
        with Session(engine) as apollo, apollo.begin():
            _authorize_workspace(apollo, APOLLO_FINANCE_ID, Permission.CLIENT_READ)
            first_pid = apollo.scalar(text("SELECT pg_backend_pid()"))
            assert set(apollo.scalars(select(ProfessionalRecordProbe.id))) == {APOLLO_RECORD_ID}

        with Session(engine) as unscoped, unscoped.begin():
            second_pid = unscoped.scalar(text("SELECT pg_backend_pid()"))
            assert list(unscoped.scalars(select(ProfessionalRecordProbe.id))) == []

        with pytest.raises(RuntimeError), Session(engine) as meridian, meridian.begin():
            _authorize_workspace(meridian, MERIDIAN_RETAIL_ID, Permission.CLIENT_READ)
            third_pid = meridian.scalar(text("SELECT pg_backend_pid()"))
            assert set(meridian.scalars(select(ProfessionalRecordProbe.id))) == {MERIDIAN_RECORD_ID}
            raise RuntimeError("force rollback")

        with Session(engine) as final_unscoped, final_unscoped.begin():
            fourth_pid = final_unscoped.scalar(text("SELECT pg_backend_pid()"))
            assert list(final_unscoped.scalars(select(ProfessionalRecordProbe.id))) == []

        assert first_pid == second_pid == third_pid == fourth_pid
    finally:
        engine.dispose()


def test_failed_persistence_discards_in_process_events_instead_of_committing_them(
    professional_record_table,
    owner_engine: Engine,
) -> None:
    event = DomainEvent(
        event_type="kernel_probe.created",
        aggregate_type="KernelProbe",
        aggregate_id=UUID("00000000-0000-4000-8000-000000001230"),
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        actor_user_id=DAVID_ID,
        actor_membership_id=DAVID_MEMBERSHIP_ID,
        request_id=UUID("00000000-0000-4000-8000-000000001231"),
        trace_id="1234567890abcdef1234567890abcdef",
        originating_channel="WEB",
    )
    collector = DomainEventCollector()
    collector.record(event)

    invalid = record_probe(
        record_id=event.aggregate_id,
        firm_id=FIRM_A_ID,
        client_id=NORTHSTAR_RETAIL_ID,
        membership_id=ALICE_MEMBERSHIP_ID,
    )
    with Session(owner_engine) as session, session.begin(), pytest.raises(IntegrityError):
        session.add(invalid)
        session.flush()

    collector.discard()
    assert collector.pending == ()
    with Session(owner_engine) as session:
        assert session.get(ProfessionalRecordProbe, event.aggregate_id) is None
