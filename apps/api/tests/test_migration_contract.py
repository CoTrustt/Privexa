from __future__ import annotations

from dataclasses import fields

from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from privexa_api.access_control.context import ClientContext
from privexa_api.db.base import Base
from privexa_api.db.resource_scope import (
    RESOURCE_SCOPE_REGISTRY,
    ResourceScope,
    validate_resource_scope_registry,
)


def test_database_is_at_revised_pbi_head(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))

    assert revision == "20260822_0018"


def test_alembic_revision_chain_is_linear(alembic_config: Config) -> None:
    script = alembic_config.attributes.get("script_directory")
    if script is None:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(alembic_config)

    head = script.get_revision("head")
    assert head is not None
    assert head.revision == "20260822_0018"
    assert head.down_revision == "20260822_0017"
    assert script.get_revision("20260822_0017").down_revision == "20260822_0016"
    assert script.get_revision("20260822_0016").down_revision == "20260822_0015"
    assert script.get_revision("20260822_0015").down_revision == "20260822_0014"
    assert script.get_revision("20260822_0014").down_revision == "20260821_0013"
    assert script.get_revision("20260821_0013").down_revision == "20260821_0012"
    assert script.get_revision("20260821_0012").down_revision == "20260821_0011"
    assert script.get_revision("20260821_0011").down_revision == "20260821_0010"
    assert script.get_revision("20260821_0010").down_revision == "20260821_0009"
    assert script.get_revision("20260821_0009").down_revision == "20260821_0008"
    assert script.get_revision("20260821_0008").down_revision == "20260821_0007"
    assert script.get_revision("20260821_0007").down_revision == "20260821_0006"
    assert script.get_revision("20260821_0006").down_revision == "20260821_0005"
    assert script.get_revision("20260821_0005").down_revision == "20260820_0004"
    assert script.get_revision("20260820_0004").down_revision == "20260820_0003"
    assert script.get_revision("20260820_0003").down_revision == "20260820_0002"
    assert script.get_revision("20260820_0002").down_revision == "20260820_0001"
    assert script.get_revision("20260820_0001").down_revision is None


def test_all_pbi_entities_have_uuid_primary_keys(owner_engine: Engine) -> None:
    inspector = inspect(owner_engine)

    for table_name in (
        "firms",
        "users",
        "firm_memberships",
        "client_workspaces",
        "client_access_grants",
        "stored_files",
        "active_client_sessions",
        "ai_policy_runtime_controls",
        "ai_provider_runtime_controls",
        "ai_provider_circuit_states",
        "ai_policy_overrides",
        "ai_executions",
        "ai_execution_events",
        "ai_execution_sources",
    ):
        primary_key = inspector.get_pk_constraint(table_name)
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert primary_key["constrained_columns"] == ["id"]
        assert str(columns["id"]["type"]) == "UUID"
        assert columns["id"]["nullable"] is False


def test_every_model_table_has_an_explicit_resource_scope() -> None:
    validate_resource_scope_registry(Base.metadata)
    assert set(RESOURCE_SCOPE_REGISTRY) == set(Base.metadata.tables)
    assert RESOURCE_SCOPE_REGISTRY["stored_files"] is ResourceScope.CLIENT


def test_ai_execution_scope_and_client_are_database_consistent(owner_engine: Engine) -> None:
    checks = {
        item["name"]: item["sqltext"]
        for item in inspect(owner_engine).get_check_constraints("ai_executions")
    }
    constraint = checks["ck_ai_executions_ai_execution_authorization_scope_client"]
    assert "authorization_scope" in constraint
    assert "client_id IS NOT NULL" in constraint
    assert "client_id IS NULL" in constraint


def test_stytch_identity_bindings_are_nullable_and_unique(owner_engine: Engine) -> None:
    inspector = inspect(owner_engine)
    firm_columns = {column["name"]: column for column in inspector.get_columns("firms")}
    membership_columns = {
        column["name"]: column for column in inspector.get_columns("firm_memberships")
    }
    firm_indexes = {index["name"]: index for index in inspector.get_indexes("firms")}
    membership_indexes = {
        index["name"]: index for index in inspector.get_indexes("firm_memberships")
    }

    assert firm_columns["stytch_organization_id"]["nullable"] is True
    assert membership_columns["stytch_member_id"]["nullable"] is True
    assert firm_indexes["uq_firms_stytch_organization_id"]["unique"] is True
    assert membership_indexes["uq_firm_memberships_stytch_member_id"]["unique"] is True


def test_rls_is_enabled_and_forced_for_protected_tables(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class "
                "WHERE relname IN ("
                "'firms', 'users', 'firm_memberships', "
                "'client_workspaces', 'client_access_grants', 'stored_files', "
                "'active_client_sessions', 'ai_policy_overrides', "
                "'ai_executions', 'ai_execution_events', 'ai_execution_sources'"
                ")"
            )
        ).all()

    assert {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows} == {
        "client_access_grants": (True, True),
        "client_workspaces": (True, True),
        "firm_memberships": (True, True),
        "firms": (True, True),
        "users": (True, True),
        "stored_files": (True, True),
        "active_client_sessions": (True, True),
        "ai_policy_overrides": (True, True),
        "ai_executions": (True, True),
        "ai_execution_events": (True, True),
        "ai_execution_sources": (True, True),
    }


def test_active_client_session_policies_are_scoped_and_command_specific(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        policies = connection.execute(
            text(
                "SELECT policyname, cmd, qual, with_check FROM pg_policies "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'active_client_sessions' ORDER BY policyname"
            )
        ).all()

    assert [(policy.policyname, policy.cmd) for policy in policies] == [
        ("active_client_sessions_scoped_insert", "INSERT"),
        ("active_client_sessions_scoped_select", "SELECT"),
        ("active_client_sessions_scoped_update", "UPDATE"),
    ]
    normalized = " ".join(f"{row.qual or ''} {row.with_check or ''}" for row in policies)
    assert "validated_firm_id" in normalized
    assert "validated_client_id" in normalized
    assert "privexa.membership_id" in normalized


def test_stored_file_policies_are_client_scoped_and_command_specific(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        policies = connection.execute(
            text(
                "SELECT policyname, cmd, qual, with_check FROM pg_policies "
                "WHERE schemaname = current_schema() AND tablename = 'stored_files' "
                "ORDER BY policyname"
            )
        ).all()

    assert [(policy.policyname, policy.cmd) for policy in policies] == [
        ("stored_files_scoped_insert", "INSERT"),
        ("stored_files_scoped_select", "SELECT"),
        ("stored_files_scoped_update", "UPDATE"),
    ]
    normalized = " ".join(f"{policy.qual or ''} {policy.with_check or ''}" for policy in policies)
    assert "validated_firm_id" in normalized
    assert "validated_client_id" in normalized
    assert "privexa.membership_id" in normalized


def test_runtime_database_role_cannot_bypass_rls(
    app_engine: Engine,
    owner_engine: Engine,
) -> None:
    with app_engine.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
    with owner_engine.connect() as connection:
        owner_role_name = connection.scalar(text("SELECT current_user"))

    assert role.rolname != owner_role_name
    assert role.rolsuper is False
    assert role.rolbypassrls is False


def test_client_workspace_policies_are_command_specific_and_default_deny(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        policies = connection.execute(
            text(
                "SELECT policyname, cmd, qual, with_check "
                "FROM pg_policies "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'client_workspaces' "
                "ORDER BY policyname"
            )
        ).all()

    assert [(policy.policyname, policy.cmd) for policy in policies] == [
        ("client_workspaces_scoped_insert", "INSERT"),
        ("client_workspaces_scoped_select", "SELECT"),
        ("client_workspaces_scoped_update", "UPDATE"),
    ]
    normalized_policy = " ".join(
        f"{policy.qual or ''} {policy.with_check or ''}" for policy in policies
    )
    for required_fragment in (
        "privexa.client_id",
        "validated_firm_id",
        "validated_client_id",
    ):
        assert required_fragment in normalized_policy


def test_client_access_grant_policy_allows_scoped_select_only(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        policies = connection.execute(
            text(
                "SELECT policyname, cmd, qual, with_check "
                "FROM pg_policies "
                "WHERE schemaname = current_schema() "
                "AND tablename = 'client_access_grants'"
            )
        ).all()

    assert [(policy.policyname, policy.cmd) for policy in policies] == [
        ("client_access_grants_scoped_select", "SELECT")
    ]
    assert policies[0].with_check is None
    normalized_policy = " ".join(str(policies[0].qual).split())
    for required_fragment in (
        "privexa.membership_id",
        "validated_firm_id",
        "validated_client_id",
    ):
        assert required_fragment in normalized_policy


def test_client_context_preserves_auditable_actor_and_tenant_dimensions() -> None:
    assert {field.name for field in fields(ClientContext)} == {
        "user_id",
        "membership_id",
        "firm_id",
        "client_id",
        "role",
    }


def test_ai_provenance_schema_has_integrity_indexes_and_append_only_grants(
    owner_engine: Engine,
    app_engine: Engine,
) -> None:
    inspector = inspect(owner_engine)
    execution_indexes = {item["name"] for item in inspector.get_indexes("ai_executions")}
    event_uniques = {
        item["name"] for item in inspector.get_unique_constraints("ai_execution_events")
    }
    source_uniques = {
        item["name"] for item in inspector.get_unique_constraints("ai_execution_sources")
    }
    with app_engine.connect() as connection:
        privileges = connection.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = current_user AND table_name IN "
                "('ai_executions', 'ai_execution_events', 'ai_execution_sources')"
            )
        ).all()

    assert {
        "ix_ai_executions_firm_client_started",
        "ix_ai_executions_firm_client_status_started",
        "ix_ai_executions_firm_task_version_started",
        "ix_ai_executions_firm_provider_model_started",
        "ix_ai_executions_trace_id",
    }.issubset(execution_indexes)
    assert {
        "uq_ai_execution_events_sequence",
        "uq_ai_execution_events_deduplication",
    }.issubset(event_uniques)
    assert {
        "uq_ai_execution_sources_ordinal",
        "uq_ai_execution_sources_reference",
    }.issubset(source_uniques)
    by_table: dict[str, set[str]] = {}
    for row in privileges:
        by_table.setdefault(row.table_name, set()).add(row.privilege_type)
    assert by_table["ai_execution_events"] == {"SELECT", "INSERT"}
    assert by_table["ai_execution_sources"] == {"SELECT", "INSERT"}
    assert "DELETE" not in by_table["ai_executions"]


def test_ai_availability_tables_have_bounded_runtime_grants(app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        privileges = connection.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = current_user AND table_name IN "
                "('ai_provider_runtime_controls', 'ai_provider_circuit_states')"
            )
        ).all()
    by_table: dict[str, set[str]] = {}
    for row in privileges:
        by_table.setdefault(row.table_name, set()).add(row.privilege_type)

    assert by_table["ai_provider_runtime_controls"] == {"SELECT"}
    assert by_table["ai_provider_circuit_states"] == {"SELECT", "INSERT", "UPDATE"}


def test_ai_provenance_child_insert_policies_bind_rows_to_visible_parent_scope(
    owner_engine: Engine,
) -> None:
    with owner_engine.connect() as connection:
        policies = connection.execute(
            text(
                "SELECT tablename, with_check FROM pg_policies "
                "WHERE schemaname = current_schema() "
                "AND policyname IN "
                "('ai_execution_events_scoped_insert', "
                "'ai_execution_sources_scoped_insert') ORDER BY tablename"
            )
        ).all()

    assert len(policies) == 2
    for policy in policies:
        normalized = " ".join(str(policy.with_check).split())
        assert "EXISTS" in normalized
        assert "parent_execution.id" in normalized
        assert f"{policy.tablename}.execution_id" in normalized
        assert f"{policy.tablename}.client_id" in normalized
