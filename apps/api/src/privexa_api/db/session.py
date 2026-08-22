from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from privexa_api.db.errors import RuntimeDatabaseSecurityError

PROTECTED_RUNTIME_TABLES = frozenset(
    {
        "active_client_sessions",
        "ai_policy_overrides",
        "ai_executions",
        "ai_execution_events",
        "ai_execution_sources",
        "firms",
        "users",
        "firm_memberships",
        "client_workspaces",
        "client_access_grants",
        "stored_files",
    }
)


def build_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)


def validate_runtime_database_security(engine: Engine) -> None:
    """Fail startup if the API connection can bypass Privexa's RLS boundary."""

    with engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        tables = connection.execute(
            text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "pg_get_userbyid(c.relowner) AS owner_name "
                "FROM pg_class AS c "
                "JOIN pg_namespace AS n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() "
                "AND c.relname IN ("
                "'firms', 'users', 'firm_memberships', "
                "'client_workspaces', 'client_access_grants', 'stored_files', "
                "'active_client_sessions', 'ai_policy_overrides', "
                "'ai_executions', 'ai_execution_events', 'ai_execution_sources'"
                ")"
            )
        ).all()

    if role.rolsuper:
        raise RuntimeDatabaseSecurityError(code="RUNTIME_DATABASE_ROLE_IS_SUPERUSER")
    if role.rolbypassrls:
        raise RuntimeDatabaseSecurityError(code="RUNTIME_DATABASE_ROLE_BYPASSES_RLS")

    table_state = {row.relname: row for row in tables}
    if set(table_state) != PROTECTED_RUNTIME_TABLES:
        raise RuntimeDatabaseSecurityError(code="PROTECTED_TABLE_INVENTORY_INCOMPLETE")
    if any(row.owner_name == role.rolname for row in tables):
        raise RuntimeDatabaseSecurityError(code="RUNTIME_DATABASE_ROLE_OWNS_PROTECTED_TABLE")
    if any(not row.relrowsecurity or not row.relforcerowsecurity for row in tables):
        raise RuntimeDatabaseSecurityError(code="PROTECTED_TABLE_RLS_NOT_FORCED")


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        with session.begin():
            yield session
    finally:
        session.close()
