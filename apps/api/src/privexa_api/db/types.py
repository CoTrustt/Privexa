from __future__ import annotations

from enum import Enum

from sqlalchemy import Enum as SQLAlchemyEnum


def constrained_enum[EnumType: Enum](
    enum_type: type[EnumType], *, name: str
) -> SQLAlchemyEnum[EnumType]:
    """Persist enum values as strings; each model declares its named check explicitly."""
    return SQLAlchemyEnum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )
