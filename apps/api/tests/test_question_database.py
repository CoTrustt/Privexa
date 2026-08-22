from __future__ import annotations

import re
from uuid import UUID

import pytest
from fixtures.questions import question_record
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    MERIDIAN_RETAIL_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.db.professional import validate_professional_object_model
from privexa_api.questions.models import Question

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]

APOLLO_QUESTION_ID = UUID("00000000-0000-4000-8000-000000001301")
MERIDIAN_QUESTION_ID = UUID("00000000-0000-4000-8000-000000001302")
NORTHSTAR_QUESTION_ID = UUID("00000000-0000-4000-8000-000000001303")


def _principal(
    *,
    user_id: UUID,
    membership_id: UUID,
    firm_id: UUID,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=user_id,
            membership_id=membership_id,
            firm_id=firm_id,
            role=FirmRole.CONSULTANT,
        ),
        stytch_member_id=f"member-question-{user_id}",
        stytch_organization_id=f"organization-question-{firm_id}",
        stytch_member_session_id=f"session-question-{membership_id}",
    )


ALICE = _principal(
    user_id=ALICE_ID,
    membership_id=ALICE_MEMBERSHIP_ID,
    firm_id=FIRM_A_ID,
)
BOB = _principal(
    user_id=BOB_ID,
    membership_id=BOB_MEMBERSHIP_ID,
    firm_id=FIRM_B_ID,
)


def _authorize(
    session: Session,
    *,
    principal: AuthenticatedPrincipal,
    client_id: UUID,
    permission: Permission = Permission.QUESTION_READ,
) -> None:
    AccessControlService.authorize_client(
        session,
        principal=principal,
        client_id=client_id,
        permission=permission,
    )


def _seed(owner_engine: Engine) -> None:
    with Session(owner_engine) as session, session.begin():
        session.add_all(
            [
                question_record(
                    question_id=APOLLO_QUESTION_ID,
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                    title="Apollo Question",
                ),
                question_record(
                    question_id=MERIDIAN_QUESTION_ID,
                    firm_id=FIRM_A_ID,
                    client_id=MERIDIAN_RETAIL_ID,
                    membership_id=ALICE_MEMBERSHIP_ID,
                    title="Meridian Question",
                ),
                question_record(
                    question_id=NORTHSTAR_QUESTION_ID,
                    firm_id=FIRM_B_ID,
                    client_id=NORTHSTAR_RETAIL_ID,
                    membership_id=BOB_MEMBERSHIP_ID,
                    title="Northstar Question",
                ),
            ]
        )


def test_question_model_and_migration_contract(owner_engine: Engine, app_engine: Engine) -> None:
    validate_professional_object_model(Question)
    inspector = inspect(owner_engine)
    checks = {item["name"] for item in inspector.get_check_constraints("questions")}
    indexes = {item["name"] for item in inspector.get_indexes("questions")}
    foreign_keys = {item["name"] for item in inspector.get_foreign_keys("questions")}

    with owner_engine.connect() as connection:
        table = connection.execute(
            text(
                "SELECT c.relrowsecurity, c.relforcerowsecurity "
                "FROM pg_class AS c JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND c.relname = 'questions'"
            )
        ).one()
        policies = connection.execute(
            text(
                "SELECT policyname, cmd, qual, with_check FROM pg_policies "
                "WHERE schemaname = current_schema() AND tablename = 'questions'"
            )
        ).all()
    with app_engine.connect() as connection:
        grants = set(
            connection.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE grantee = current_user AND table_name = 'questions'"
                )
            ).scalars()
        )

    assert table.relrowsecurity is True
    assert table.relforcerowsecurity is True
    assert {(row.policyname, row.cmd) for row in policies} == {
        ("questions_scoped_select", "SELECT"),
        ("questions_scoped_insert", "INSERT"),
        ("questions_scoped_update", "UPDATE"),
    }
    policy_sql = " ".join(f"{row.qual or ''} {row.with_check or ''}" for row in policies)
    assert "validated_firm_id" in policy_sql
    assert "validated_client_id" in policy_sql
    assert "privexa.membership_id" in policy_sql
    assert grants == {"SELECT", "INSERT"}
    assert {
        "ck_questions_question_status",
        "ck_questions_question_title_valid",
        "ck_questions_question_text_valid",
        "ck_questions_question_context_valid",
        "ck_questions_version_positive",
        "ck_questions_timestamps_ordered",
    } <= checks
    assert {
        "ix_questions_firm_client_created",
        "ix_questions_firm_client_status_created_id",
    } <= indexes
    assert {
        "fk_questions_firm_client",
        "fk_questions_firm_creator_membership",
        "fk_questions_firm_updater_membership",
    } <= foreign_keys


def test_unfiltered_runtime_queries_and_writes_are_client_isolated(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed(owner_engine)

    with Session(app_engine) as session, session.begin():
        _authorize(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        visible = set(session.scalars(select(Question.id)))
        same_firm = session.get(Question, MERIDIAN_QUESTION_ID)
        cross_firm = session.get(Question, NORTHSTAR_QUESTION_ID)
        foreign_update = session.execute(
            text("UPDATE questions SET title = 'Compromised' WHERE id = :id"),
            {"id": MERIDIAN_QUESTION_ID},
        ).rowcount

    with Session(app_engine) as session, session.begin():
        missing_count = session.scalar(text("SELECT count(*) FROM questions"))
        missing_update = session.execute(
            text("UPDATE questions SET title = 'Unscoped' WHERE id = :id"),
            {"id": APOLLO_QUESTION_ID},
        ).rowcount

    assert visible == {APOLLO_QUESTION_ID}
    assert same_firm is None
    assert cross_firm is None
    assert foreign_update == 0
    assert missing_count == 0
    assert missing_update == 0

    with Session(owner_engine) as session:
        assert session.get(Question, MERIDIAN_QUESTION_ID).title == "Meridian Question"
        assert session.get(Question, APOLLO_QUESTION_ID).title == "Apollo Question"


def test_rls_rejects_forged_actor_ownership_and_hard_delete(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    _seed(owner_engine)
    forged = question_record(
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        membership_id=BOB_MEMBERSHIP_ID,
    )
    with Session(app_engine) as session, session.begin():
        _authorize(
            session,
            principal=ALICE,
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.QUESTION_CREATE,
        )
        session.add(forged)
        with pytest.raises(DBAPIError):
            session.flush()

    with Session(app_engine) as session, session.begin():
        _authorize(
            session,
            principal=ALICE,
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.QUESTION_UPDATE,
        )
        question = session.get(Question, APOLLO_QUESTION_ID)
        assert question is not None
        question.client_id = MERIDIAN_RETAIL_ID
        with pytest.raises(DBAPIError):
            session.flush()

    with Session(app_engine) as session, session.begin():
        _authorize(
            session,
            principal=ALICE,
            client_id=APOLLO_FINANCE_ID,
            permission=Permission.QUESTION_UPDATE,
        )
        question = session.get(Question, APOLLO_QUESTION_ID)
        assert question is not None
        session.delete(question)
        with pytest.raises(DBAPIError):
            session.flush()


def test_question_context_does_not_leak_through_reused_pooled_connection(
    tenant_data,
    owner_engine: Engine,
    app_database_url: str,
) -> None:
    _seed(owner_engine)
    assert re.fullmatch(r"postgresql\+psycopg://.+", app_database_url)
    engine = create_engine(app_database_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    try:
        with Session(engine) as apollo, apollo.begin():
            _authorize(apollo, principal=ALICE, client_id=APOLLO_FINANCE_ID)
            first_pid = apollo.scalar(text("SELECT pg_backend_pid()"))
            assert set(apollo.scalars(select(Question.id))) == {APOLLO_QUESTION_ID}

        with Session(engine) as missing, missing.begin():
            second_pid = missing.scalar(text("SELECT pg_backend_pid()"))
            assert list(missing.scalars(select(Question.id))) == []

        with pytest.raises(RuntimeError), Session(engine) as northstar, northstar.begin():
            _authorize(northstar, principal=BOB, client_id=NORTHSTAR_RETAIL_ID)
            third_pid = northstar.scalar(text("SELECT pg_backend_pid()"))
            assert set(northstar.scalars(select(Question.id))) == {NORTHSTAR_QUESTION_ID}
            raise RuntimeError("force rollback")

        with Session(engine) as final_missing, final_missing.begin():
            fourth_pid = final_missing.scalar(text("SELECT pg_backend_pid()"))
            assert list(final_missing.scalars(select(Question.id))) == []

        assert first_pid == second_pid == third_pid == fourth_pid
    finally:
        engine.dispose()
