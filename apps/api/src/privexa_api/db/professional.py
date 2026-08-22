from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Table,
    UniqueConstraint,
    Uuid,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column
from sqlalchemy.schema import SchemaItem

_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class ClientOwnedMixin:
    """Required tenant columns for a client-owned professional record."""

    firm_id: Mapped[UUID] = mapped_column(nullable=False)
    client_id: Mapped[UUID] = mapped_column(nullable=False)


class ActorProvenanceMixin:
    """Current creator/updater attribution; this is not an audit-history substitute."""

    created_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)
    updated_by_membership_id: Mapped[UUID] = mapped_column(nullable=False)


class VersionedMixin:
    """Opt-in SQLAlchemy optimistic concurrency for mutable professional records."""

    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}


class ArchivableMixin:
    """Opt-in professional-record archival, distinct from privacy erasure."""

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_by_membership_id: Mapped[UUID | None] = mapped_column()


def professional_object_constraints(
    table_name: str,
    *,
    archivable: bool = False,
) -> tuple[SchemaItem, ...]:
    """Return the explicit integrity contract a concrete professional table must adopt."""

    if not _SAFE_IDENTIFIER.fullmatch(table_name):
        raise ValueError("table_name must be a safe PostgreSQL identifier")

    constraints: list[SchemaItem] = [
        ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name=f"fk_{table_name}_firm_client",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "created_by_membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name=f"fk_{table_name}_firm_creator_membership",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["firm_id", "updated_by_membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name=f"fk_{table_name}_firm_updater_membership",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("firm_id", "client_id", "id", name=f"uq_{table_name}_tenant_id"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "updated_at >= created_at",
            name="timestamps_ordered",
        ),
        Index(
            f"ix_{table_name}_firm_client_created",
            "firm_id",
            "client_id",
            "created_at",
        ),
    ]
    if archivable:
        constraints.extend(
            [
                ForeignKeyConstraint(
                    ["firm_id", "archived_by_membership_id"],
                    ["firm_memberships.firm_id", "firm_memberships.id"],
                    name=f"fk_{table_name}_firm_archiver_membership",
                    ondelete="RESTRICT",
                ),
                CheckConstraint(
                    "(archived_at IS NULL AND archived_by_membership_id IS NULL) OR "
                    "(archived_at IS NOT NULL AND archived_by_membership_id IS NOT NULL)",
                    name="archive_provenance_complete",
                ),
                CheckConstraint(
                    "archived_at IS NULL OR archived_at >= created_at",
                    name="archive_timestamp_ordered",
                ),
                Index(
                    f"ix_{table_name}_firm_client_archived",
                    "firm_id",
                    "client_id",
                    "archived_at",
                ),
            ]
        )
    return tuple(constraints)


def validate_professional_object_model(
    model: type[object],
    *,
    archivable: bool = False,
) -> None:
    """Fail startup/tests when a mapped professional object omits a kernel invariant."""

    mapper = inspect(model)
    table: Table = mapper.local_table
    required_columns = {
        "id",
        "firm_id",
        "client_id",
        "created_at",
        "updated_at",
        "created_by_membership_id",
        "updated_by_membership_id",
        "version",
    }
    if archivable:
        required_columns |= {"archived_at", "archived_by_membership_id"}
    missing = sorted(required_columns - set(table.columns.keys()))
    if missing:
        raise RuntimeError(f"professional object {table.name} is missing columns: {missing}")

    non_nullable = required_columns - {"archived_at", "archived_by_membership_id"}
    nullable = sorted(name for name in non_nullable if table.columns[name].nullable)
    if nullable:
        raise RuntimeError(
            f"professional object {table.name} has nullable required columns: {nullable}"
        )

    if mapper.version_id_col is not table.columns["version"]:
        raise RuntimeError(f"professional object {table.name} must enable optimistic versioning")

    identity_column = table.columns["id"]
    if not identity_column.primary_key or not isinstance(identity_column.type, Uuid):
        raise RuntimeError(f"professional object {table.name} requires a UUID primary key")

    version_column = table.columns["version"]
    if not isinstance(version_column.type, Integer) or version_column.server_default is None:
        raise RuntimeError(
            f"professional object {table.name} requires a database-defaulted integer version"
        )

    timestamp_columns = (table.columns["created_at"], table.columns["updated_at"])
    if any(
        not isinstance(column.type, DateTime) or not column.type.timezone
        for column in timestamp_columns
    ):
        raise RuntimeError(f"professional object {table.name} requires timezone-aware timestamps")
    if any(column.server_default is None for column in timestamp_columns):
        raise RuntimeError(f"professional object {table.name} requires database timestamp defaults")
    if table.columns["updated_at"].onupdate is None:
        raise RuntimeError(f"professional object {table.name} requires an ORM update timestamp")

    foreign_key_shapes = {
        (
            frozenset(element.parent.name for element in constraint.elements),
            frozenset(element.target_fullname for element in constraint.elements),
        )
        for constraint in table.foreign_key_constraints
    }
    required_foreign_keys = {
        (
            frozenset({"firm_id", "client_id"}),
            frozenset({"client_workspaces.firm_id", "client_workspaces.id"}),
        ),
        (
            frozenset({"firm_id", "created_by_membership_id"}),
            frozenset({"firm_memberships.firm_id", "firm_memberships.id"}),
        ),
        (
            frozenset({"firm_id", "updated_by_membership_id"}),
            frozenset({"firm_memberships.firm_id", "firm_memberships.id"}),
        ),
    }
    if archivable:
        required_foreign_keys.add(
            (
                frozenset({"firm_id", "archived_by_membership_id"}),
                frozenset({"firm_memberships.firm_id", "firm_memberships.id"}),
            )
        )
    if missing_foreign_keys := required_foreign_keys - foreign_key_shapes:
        raise RuntimeError(
            f"professional object {table.name} is missing composite ownership foreign keys: "
            f"{len(missing_foreign_keys)}"
        )

    has_tenant_identity = any(
        set(constraint.columns.keys()) == {"firm_id", "client_id", "id"}
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    )
    if not has_tenant_identity:
        raise RuntimeError(
            f"professional object {table.name} requires unique firm/client/object identity"
        )

    constraint_names = {
        constraint.name or "" for constraint in table.constraints if constraint.name is not None
    }
    required_constraint_suffixes = {"version_positive", "timestamps_ordered"}
    if archivable:
        required_constraint_suffixes |= {
            "archive_provenance_complete",
            "archive_timestamp_ordered",
        }
    missing_checks = sorted(
        suffix
        for suffix in required_constraint_suffixes
        if not any(name.endswith(suffix) for name in constraint_names)
    )
    if missing_checks:
        raise RuntimeError(
            f"professional object {table.name} is missing check constraints: {missing_checks}"
        )

    index_shapes = {tuple(column.name for column in index.columns) for index in table.indexes}
    required_indexes = {("firm_id", "client_id", "created_at")}
    if archivable:
        required_indexes.add(("firm_id", "client_id", "archived_at"))
    if missing_indexes := required_indexes - index_shapes:
        raise RuntimeError(
            f"professional object {table.name} is missing tenant indexes: {sorted(missing_indexes)}"
        )
