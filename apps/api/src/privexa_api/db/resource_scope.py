from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType

from sqlalchemy import MetaData


class ResourceScope(StrEnum):
    SYSTEM = "SYSTEM"
    GLOBAL_IDENTITY = "GLOBAL_IDENTITY"
    FIRM = "FIRM"
    CLIENT_CONTROL = "CLIENT_CONTROL"
    CLIENT = "CLIENT"
    FIRM_OR_CLIENT = "FIRM_OR_CLIENT"


RESOURCE_SCOPE_REGISTRY = MappingProxyType(
    {
        "ai_policy_runtime_controls": ResourceScope.SYSTEM,
        "ai_provider_runtime_controls": ResourceScope.SYSTEM,
        "ai_provider_circuit_states": ResourceScope.SYSTEM,
        "users": ResourceScope.GLOBAL_IDENTITY,
        "firms": ResourceScope.FIRM,
        "firm_memberships": ResourceScope.FIRM,
        "client_workspaces": ResourceScope.CLIENT_CONTROL,
        "client_access_grants": ResourceScope.CLIENT_CONTROL,
        "active_client_sessions": ResourceScope.CLIENT_CONTROL,
        "stored_files": ResourceScope.CLIENT,
        "ai_policy_overrides": ResourceScope.FIRM_OR_CLIENT,
        "ai_executions": ResourceScope.FIRM_OR_CLIENT,
        "ai_execution_events": ResourceScope.FIRM_OR_CLIENT,
        "ai_execution_sources": ResourceScope.FIRM_OR_CLIENT,
    }
)


def validate_resource_scope_registry(metadata: MetaData) -> None:
    """Fail startup/model discovery when a table lacks an explicit isolation class."""

    model_tables = set(metadata.tables)
    registered_tables = set(RESOURCE_SCOPE_REGISTRY)
    if model_tables != registered_tables:
        missing = sorted(model_tables - registered_tables)
        stale = sorted(registered_tables - model_tables)
        raise RuntimeError(f"resource scope registry mismatch; missing={missing}, stale={stale}")

    for table_name, scope in RESOURCE_SCOPE_REGISTRY.items():
        if scope is not ResourceScope.CLIENT:
            continue
        table = metadata.tables[table_name]
        for column_name in ("firm_id", "client_id"):
            column = table.columns.get(column_name)
            if column is None or column.nullable:
                raise RuntimeError(f"client resource {table_name} requires non-null {column_name}")
        has_composite_owner = any(
            {element.parent.name for element in constraint.elements} == {"firm_id", "client_id"}
            for constraint in table.foreign_key_constraints
        )
        if not has_composite_owner:
            raise RuntimeError(
                f"client resource {table_name} requires composite firm/client ownership"
            )
