from __future__ import annotations

from dataclasses import fields

from alembic.config import Config
from sqlalchemy import Engine, inspect, text

from privexa_api.access_control.context import ClientContext


def test_database_is_at_revised_pbi_head(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))

    assert revision == "20260821_0007"


def test_alembic_revision_chain_is_linear(alembic_config: Config) -> None:
    script = alembic_config.attributes.get("script_directory")
    if script is None:
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(alembic_config)

    head = script.get_revision("head")
    assert head is not None
    assert head.revision == "20260821_0007"
    assert head.down_revision == "20260821_0006"
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
    ):
        primary_key = inspector.get_pk_constraint(table_name)
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert primary_key["constrained_columns"] == ["id"]
        assert str(columns["id"]["type"]) == "UUID"
        assert columns["id"]["nullable"] is False


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
                "'client_workspaces', 'client_access_grants'"
                ")"
            )
        ).all()

    assert {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows} == {
        "client_access_grants": (True, True),
        "client_workspaces": (True, True),
        "firm_memberships": (True, True),
        "firms": (True, True),
        "users": (True, True),
    }


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
