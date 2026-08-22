from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn
from alembic.config import Config
from fastapi import FastAPI
from fixtures.authorization import MultiIdentityStytchGateway
from fixtures.storage import FakeObjectStorageGateway
from fixtures.tenant_foundation import persist_tenant_foundation_fixture
from sqlalchemy import text
from sqlalchemy.orm import Session

from alembic import command
from privexa_api.config import Settings
from privexa_api.db.session import build_engine, build_session_factory
from privexa_api.main import create_app

API_ROOT = Path(__file__).resolve().parents[1]


def _required_url(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required for the full-stack browser test")
    database_name = urlsplit(value.replace("postgresql+psycopg", "postgresql", 1)).path.lstrip("/")
    if not database_name.lower().endswith("_test"):
        raise RuntimeError(f"{name} must target a database ending in '_test'")
    return value


def _prepare_test_database(owner_database_url: str, app_database_url: str) -> None:
    os.environ["DATABASE_URL"] = owner_database_url
    os.environ["APP_DATABASE_URL"] = app_database_url
    configuration = Config(str(API_ROOT / "alembic.ini"))
    command.upgrade(configuration, "head")

    owner_engine = build_engine(owner_database_url)
    try:
        with Session(owner_engine, expire_on_commit=False) as session, session.begin():
            session.execute(
                text(
                    "TRUNCATE TABLE ai_execution_sources, ai_execution_events, ai_executions, "
                    "ai_provider_circuit_states, ai_policy_overrides, active_client_sessions, "
                    "questions, stored_files, client_access_grants, firm_memberships, "
                    "client_workspaces, users, firms"
                )
            )
            persist_tenant_foundation_fixture(session)
    finally:
        owner_engine.dispose()


def build_e2e_app() -> FastAPI:
    if os.getenv("PRIVEXA_ENVIRONMENT") != "test":
        raise RuntimeError("The full-stack browser server requires PRIVEXA_ENVIRONMENT=test")
    owner_database_url = _required_url("TEST_DATABASE_URL")
    app_database_url = _required_url("TEST_APP_DATABASE_URL")
    _prepare_test_database(owner_database_url, app_database_url)

    os.environ["APP_DATABASE_URL"] = app_database_url
    settings = Settings()
    app_engine = build_engine(app_database_url)
    return create_app(
        settings=settings,
        stytch_gateway=MultiIdentityStytchGateway(),
        object_storage_gateway=FakeObjectStorageGateway(),
        session_factory=build_session_factory(app_engine),
    )


app = build_e2e_app()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.getenv("PRIVEXA_E2E_API_PORT", "4020")),
        log_level="warning",
    )
