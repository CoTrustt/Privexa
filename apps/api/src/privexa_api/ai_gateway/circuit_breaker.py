from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session, sessionmaker

from privexa_api.ai_gateway.models import AIProviderCircuitState
from privexa_api.ai_gateway.routing import AIModelRoute


class AICircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class AICircuitPermit:
    allowed: bool
    state: AICircuitState
    retry_after_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class AICircuitSettings:
    failure_threshold: int = 5
    failure_window_seconds: int = 60
    open_seconds: int = 30
    half_open_success_threshold: int = 2
    probe_lease_seconds: int = 10

    def __post_init__(self) -> None:
        if (
            min(
                self.failure_threshold,
                self.failure_window_seconds,
                self.open_seconds,
                self.half_open_success_threshold,
                self.probe_lease_seconds,
            )
            < 1
        ):
            raise ValueError("AI circuit settings must be positive")


class AICircuitBreaker(Protocol):
    def peek(self, route: AIModelRoute) -> AICircuitPermit: ...

    def before_call(self, route: AIModelRoute) -> AICircuitPermit: ...

    def record_success(self, route: AIModelRoute) -> None: ...

    def record_failure(self, route: AIModelRoute) -> None: ...


@dataclass(slots=True)
class _MemoryState:
    state: AICircuitState = AICircuitState.CLOSED
    failure_count: int = 0
    window_started_at: datetime | None = None
    opened_at: datetime | None = None
    half_open_successes: int = 0
    probe_lease_until: datetime | None = None


class InMemoryAICircuitBreaker:
    """Concurrency-safe test/development implementation; production uses PostgreSQL."""

    def __init__(
        self,
        settings: AICircuitSettings | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings or AICircuitSettings()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._states: dict[tuple[str, str, str], _MemoryState] = {}
        self._lock = Lock()

    def peek(self, route: AIModelRoute) -> AICircuitPermit:
        with self._lock:
            return self._evaluate(route, acquire_probe=False)

    def before_call(self, route: AIModelRoute) -> AICircuitPermit:
        with self._lock:
            return self._evaluate(route, acquire_probe=True)

    def record_success(self, route: AIModelRoute) -> None:
        with self._lock:
            now = self._clock()
            for key in _route_keys(route):
                _apply_success(self._states.setdefault(key, _MemoryState()), now, self._settings)

    def record_failure(self, route: AIModelRoute) -> None:
        with self._lock:
            now = self._clock()
            for key in _route_keys(route):
                _apply_failure(self._states.setdefault(key, _MemoryState()), now, self._settings)

    def _evaluate(self, route: AIModelRoute, *, acquire_probe: bool) -> AICircuitPermit:
        now = self._clock()
        states = [self._states.setdefault(key, _MemoryState()) for key in _route_keys(route)]
        permits = [
            _permit(state, now, self._settings, transition=acquire_probe) for state in states
        ]
        denied = next((permit for permit in permits if not permit.allowed), None)
        if denied is not None:
            return denied
        if acquire_probe:
            for state in states:
                if AICircuitState(state.state) is AICircuitState.HALF_OPEN:
                    state.probe_lease_until = now + timedelta(
                        seconds=self._settings.probe_lease_seconds
                    )
        state = max((permit.state for permit in permits), key=_state_rank)
        return AICircuitPermit(allowed=True, state=state)


class DatabaseAICircuitBreaker:
    """Cluster-shared circuit state using short row-locked PostgreSQL transactions."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: AICircuitSettings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or AICircuitSettings()

    def peek(self, route: AIModelRoute) -> AICircuitPermit:
        with self._session_factory() as session, session.begin():
            states = self._load_states(session, route, lock=False)
            permits = [
                _permit(row, datetime.now(UTC), self._settings, transition=False) for row in states
            ]
            denied = next((permit for permit in permits if not permit.allowed), None)
            if denied is not None:
                return denied
            state = max((permit.state for permit in permits), key=_state_rank)
            return AICircuitPermit(allowed=True, state=state)

    def before_call(self, route: AIModelRoute) -> AICircuitPermit:
        with self._session_factory() as session, session.begin():
            states = self._load_states(session, route, lock=True)
            now = datetime.now(UTC)
            permits = [_permit(row, now, self._settings, transition=True) for row in states]
            denied = next((permit for permit in permits if not permit.allowed), None)
            if denied is not None:
                return denied
            for row in states:
                if row.state == AICircuitState.HALF_OPEN.value:
                    row.probe_lease_until = now + timedelta(
                        seconds=self._settings.probe_lease_seconds
                    )
            state = max((permit.state for permit in permits), key=_state_rank)
            return AICircuitPermit(allowed=True, state=state)

    def record_success(self, route: AIModelRoute) -> None:
        self._record(route, success=True)

    def record_failure(self, route: AIModelRoute) -> None:
        self._record(route, success=False)

    def _record(self, route: AIModelRoute, *, success: bool) -> None:
        with self._session_factory() as session, session.begin():
            states = self._load_states(session, route, lock=True)
            now = datetime.now(UTC)
            for row in states:
                if success:
                    _apply_success(row, now, self._settings)
                else:
                    _apply_failure(row, now, self._settings)

    def _load_states(
        self,
        session: Session,
        route: AIModelRoute,
        *,
        lock: bool,
    ) -> list[AIProviderCircuitState]:
        keys = _route_keys(route)
        for scope_type, provider_id, provider_model in keys:
            session.execute(
                postgresql_insert(AIProviderCircuitState)
                .values(
                    scope_type=scope_type,
                    provider_id=provider_id,
                    provider_model=provider_model,
                    state=AICircuitState.CLOSED.value,
                    failure_count=0,
                    half_open_successes=0,
                )
                .on_conflict_do_nothing(
                    index_elements=("scope_type", "provider_id", "provider_model")
                )
            )
        statement = select(AIProviderCircuitState).where(
            AIProviderCircuitState.provider_id == route.provider.value,
            AIProviderCircuitState.scope_type.in_(("PROVIDER", "PROVIDER_MODEL")),
            AIProviderCircuitState.provider_model.in_(("", route.provider_model)),
        )
        if lock:
            statement = statement.with_for_update()
        rows = session.scalars(statement.order_by(AIProviderCircuitState.scope_type)).all()
        if len(rows) != 2:
            raise RuntimeError("AI circuit state could not be established")
        return list(rows)


def _route_keys(route: AIModelRoute) -> tuple[tuple[str, str, str], ...]:
    return (
        ("PROVIDER", route.provider.value, ""),
        ("PROVIDER_MODEL", route.provider.value, route.provider_model),
    )


def _permit(
    state: _MemoryState | AIProviderCircuitState,
    now: datetime,
    settings: AICircuitSettings,
    *,
    transition: bool,
) -> AICircuitPermit:
    current = AICircuitState(state.state)
    if current is AICircuitState.OPEN:
        opened_at = state.opened_at or now
        remaining = settings.open_seconds - int((now - opened_at).total_seconds())
        if remaining > 0:
            return AICircuitPermit(False, current, max(1, remaining))
        if transition:
            state.state = AICircuitState.HALF_OPEN.value
            state.half_open_successes = 0
            state.probe_lease_until = None
        current = AICircuitState.HALF_OPEN
    if current is AICircuitState.HALF_OPEN and (
        state.probe_lease_until is not None and state.probe_lease_until > now
    ):
        remaining = max(1, int((state.probe_lease_until - now).total_seconds()))
        return AICircuitPermit(False, current, remaining)
    return AICircuitPermit(True, current)


def _apply_success(
    state: _MemoryState | AIProviderCircuitState,
    now: datetime,
    settings: AICircuitSettings,
) -> None:
    if AICircuitState(state.state) is AICircuitState.HALF_OPEN:
        state.half_open_successes += 1
        state.probe_lease_until = None
        if state.half_open_successes < settings.half_open_success_threshold:
            return
    state.state = AICircuitState.CLOSED.value
    state.failure_count = 0
    state.window_started_at = None
    state.opened_at = None
    state.half_open_successes = 0
    state.probe_lease_until = None


def _apply_failure(
    state: _MemoryState | AIProviderCircuitState,
    now: datetime,
    settings: AICircuitSettings,
) -> None:
    if AICircuitState(state.state) is AICircuitState.HALF_OPEN:
        _open(state, now)
        return
    if (
        state.window_started_at is None
        or (now - state.window_started_at).total_seconds() > settings.failure_window_seconds
    ):
        state.window_started_at = now
        state.failure_count = 0
    state.failure_count += 1
    if state.failure_count >= settings.failure_threshold:
        _open(state, now)


def _open(state: _MemoryState | AIProviderCircuitState, now: datetime) -> None:
    state.state = AICircuitState.OPEN.value
    state.opened_at = now
    state.half_open_successes = 0
    state.probe_lease_until = None


def _state_rank(value: AICircuitState) -> int:
    return {
        AICircuitState.CLOSED: 0,
        AICircuitState.HALF_OPEN: 1,
        AICircuitState.OPEN: 2,
    }[value]
