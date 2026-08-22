from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

EventType = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$",
    ),
]
AggregateType = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Z][A-Za-z0-9]*$"),
]
TraceId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]


class DomainEvent(BaseModel):
    """Immutable in-process event envelope; it is not an audit row or integration message."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, validate_default=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    aggregate_type: AggregateType
    aggregate_id: UUID
    firm_id: UUID
    client_id: UUID
    actor_user_id: UUID
    actor_membership_id: UUID
    request_id: UUID
    trace_id: TraceId | None
    originating_channel: str = Field(min_length=1, max_length=32)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = Field(default=1, ge=1)
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(UTC)


class DomainEventCollector:
    """Small unit-of-work-local buffer for events produced during one domain operation."""

    __slots__ = ("_pending",)

    def __init__(self) -> None:
        self._pending: list[DomainEvent] = []

    @property
    def pending(self) -> tuple[DomainEvent, ...]:
        return tuple(self._pending)

    def record(self, event: DomainEvent) -> None:
        if not isinstance(event, DomainEvent):
            raise TypeError("event must be a DomainEvent")
        self._pending.append(event)

    def drain(self) -> tuple[DomainEvent, ...]:
        """Return events after a successful commit and empty the local buffer."""

        events = tuple(self._pending)
        self._pending.clear()
        return events

    def discard(self) -> None:
        """Drop locally collected events when the unit of work rolls back."""

        self._pending.clear()
