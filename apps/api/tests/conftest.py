from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fixtures.tenant_foundation import (
    TenantFoundationFixture,
    persist_tenant_foundation_fixture,
)
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from alembic import command
from privexa_api.db.session import build_engine

API_ROOT = Path(__file__).resolve().parents[1]


def _required_url(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise pytest.UsageError(f"{name} must be set for PostgreSQL integration tests")
    return value


def _assert_test_database(engine: Engine) -> None:
    with engine.connect() as connection:
        database_name = connection.scalar(text("SELECT current_database()"))
    if not database_name or not database_name.lower().endswith("_test"):
        raise pytest.UsageError(
            "Refusing destructive tests against a database whose name does not end "
            f"in '_test': {database_name!r}"
        )


@pytest.fixture(scope="session")
def owner_database_url() -> str:
    return _required_url("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def app_database_url() -> str:
    return _required_url("TEST_APP_DATABASE_URL")


@pytest.fixture(scope="session")
def owner_engine(owner_database_url: str) -> Iterator[Engine]:
    engine = build_engine(owner_database_url)
    _assert_test_database(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(app_database_url: str) -> Iterator[Engine]:
    engine = build_engine(app_database_url)
    _assert_test_database(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def alembic_config(owner_database_url: str, app_database_url: str) -> Config:
    os.environ["DATABASE_URL"] = owner_database_url
    os.environ["APP_DATABASE_URL"] = app_database_url
    return Config(str(API_ROOT / "alembic.ini"))


@pytest.fixture(scope="session", autouse=True)
def migrated_database(alembic_config: Config, owner_engine: Engine) -> None:
    command.upgrade(alembic_config, "head")
    _assert_test_database(owner_engine)


@pytest.fixture
def tenant_data(owner_engine: Engine, migrated_database: None) -> TenantFoundationFixture:
    with Session(owner_engine, expire_on_commit=False) as session, session.begin():
        session.execute(
            text(
                "TRUNCATE TABLE ai_execution_sources, ai_execution_events, ai_executions, "
                "ai_provider_circuit_states, "
                "ai_policy_overrides, active_client_sessions, questions, stored_files, "
                "client_access_grants, "
                "firm_memberships, client_workspaces, users, firms"
            )
        )
        fixture = persist_tenant_foundation_fixture(session)
    return fixture
