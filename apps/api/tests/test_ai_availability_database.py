from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fixtures.ai_gateway import build_test_model_route
from sqlalchemy import Engine, inspect, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from privexa_api.ai_gateway.circuit_breaker import (
    AICircuitSettings,
    DatabaseAICircuitBreaker,
)
from privexa_api.ai_gateway.models import AIProviderCircuitState, AIProviderRuntimeControl
from privexa_api.ai_gateway.provider_controls import DatabaseAIProviderControlRepository
from privexa_api.ai_gateway.routing import AIProviderName
from privexa_api.db.session import build_session_factory


def test_seeded_provider_controls_are_enabled_and_runtime_read_only(
    app_engine: Engine,
) -> None:
    repository = DatabaseAIProviderControlRepository(build_session_factory(app_engine))

    assert repository.is_enabled(AIProviderName.OPENROUTER) is True
    assert repository.is_enabled(AIProviderName.DETERMINISTIC) is True

    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        session.execute(
            update(AIProviderRuntimeControl)
            .where(AIProviderRuntimeControl.provider_id == AIProviderName.OPENROUTER.value)
            .values(enabled=False)
        )
    assert getattr(error.value.orig, "sqlstate", None) == "42501"


def test_circuit_state_is_shared_between_breaker_instances(
    app_engine: Engine,
    tenant_data,
) -> None:
    factory = build_session_factory(app_engine)
    settings = AICircuitSettings(failure_threshold=2, failure_window_seconds=60)
    first = DatabaseAICircuitBreaker(factory, settings)
    second = DatabaseAICircuitBreaker(factory, settings)
    route = build_test_model_route()

    assert first.before_call(route).allowed is True
    first.record_failure(route)
    assert second.before_call(route).allowed is True
    second.record_failure(route)

    blocked = first.before_call(route)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds is not None
    with Session(app_engine) as session, session.begin():
        states = session.scalars(
            select(AIProviderCircuitState).where(
                AIProviderCircuitState.provider_id == route.provider.value
            )
        ).all()
        state_values = [state.state for state in states]
    assert len(state_values) == 2
    assert set(state_values) == {"OPEN"}


def test_circuit_schema_contains_only_operational_health_fields(owner_engine: Engine) -> None:
    columns = {
        item["name"] for item in inspect(owner_engine).get_columns("ai_provider_circuit_states")
    }

    assert columns == {
        "id",
        "scope_type",
        "provider_id",
        "provider_model",
        "state",
        "failure_count",
        "window_started_at",
        "opened_at",
        "half_open_successes",
        "probe_lease_until",
        "created_at",
        "updated_at",
    }
    assert not columns.intersection({"firm_id", "client_id", "prompt", "content", "output"})


def test_concurrent_database_failure_storm_opens_consistent_shared_state(
    app_engine: Engine,
    tenant_data,
) -> None:
    factory = build_session_factory(app_engine)
    breaker = DatabaseAICircuitBreaker(
        factory,
        AICircuitSettings(failure_threshold=5, failure_window_seconds=60),
    )
    route = build_test_model_route()

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda _: breaker.record_failure(route), range(16)))
        permits = list(executor.map(lambda _: breaker.before_call(route), range(16)))

    assert all(not permit.allowed for permit in permits)
    with Session(app_engine) as session, session.begin():
        states = session.scalars(
            select(AIProviderCircuitState).where(
                AIProviderCircuitState.provider_id == route.provider.value
            )
        ).all()
        state_values = [(state.state, state.failure_count) for state in states]
    assert len(state_values) == 2
    assert {state for state, _ in state_values} == {"OPEN"}
    assert all(failure_count >= 5 for _, failure_count in state_values)
