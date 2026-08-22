from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fixtures.ai_gateway import (
    NOOP_AI_PROVENANCE,
    FakeAIProvider,
    build_test_model_route,
    trusted_ai_context,
)

from privexa_api.access_control.permissions import Permission
from privexa_api.ai_gateway.availability import (
    AIAvailabilityReason,
    AIAvailabilityService,
)
from privexa_api.ai_gateway.circuit_breaker import (
    AICircuitSettings,
    AICircuitState,
    InMemoryAICircuitBreaker,
)
from privexa_api.ai_gateway.contracts import AIExecutionRequest, AIExecutionStatus, AIModelAlias
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.provider_controls import StaticAIProviderControlRepository
from privexa_api.ai_gateway.providers.base import AIProviderRequest, AIProviderResult
from privexa_api.ai_gateway.routing import AIModelRouter, AIProviderName
from privexa_api.ai_gateway.tasks import (
    PrepareWorkNoteInput,
    SyntheticTextSummaryInput,
    build_task_registry,
)
from privexa_api.ai_gateway.telemetry import AIExecutionTelemetry
from privexa_api.ai_policy.contracts import AIModelClass, AIPolicyRuntimeSnapshot, AIProviderClass
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel


class FailingProvider(FakeAIProvider):
    def __init__(self, category: AIErrorCategory = AIErrorCategory.PROVIDER_UNAVAILABLE) -> None:
        super().__init__()
        self.category = category

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.requests.append(request)
        raise ProviderFailure(category=self.category, retryable=True)


class MutablePolicyRepository(StaticAIPolicyRepository):
    def __init__(self) -> None:
        self.global_enabled = True
        self.task_enabled = True

    def load(self, session, *, context, task, sensitivity) -> AIPolicyRuntimeSnapshot:
        return AIPolicyRuntimeSnapshot(
            global_enabled=self.global_enabled,
            task_enabled=self.task_enabled,
        )


class TaskAwarePolicyRepository(StaticAIPolicyRepository):
    def load(self, session, *, context, task, sensitivity) -> AIPolicyRuntimeSnapshot:
        return AIPolicyRuntimeSnapshot(
            global_enabled=True,
            task_enabled=task is not AITaskType.PREPARE_WORK_NOTE,
        )


class DisablingProvider(FakeAIProvider):
    def __init__(self, repository: MutablePolicyRepository) -> None:
        super().__init__()
        self.repository = repository

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        result = await super().execute(request)
        self.repository.global_enabled = False
        return result


class MutableProviderControlRepository:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled

    def is_enabled(self, provider: AIProviderName) -> bool:
        assert provider is AIProviderName.OPENROUTER
        return self.enabled


class ExplodingProviderControlRepository:
    def is_enabled(self, provider: AIProviderName) -> bool:
        assert provider is AIProviderName.OPENROUTER
        raise RuntimeError("synthetic control-plane failure")


class ExplodingCircuit:
    def peek(self, route):  # type: ignore[no-untyped-def]
        del route
        raise RuntimeError("synthetic circuit-store failure")

    def before_call(self, route):  # type: ignore[no-untyped-def]
        del route
        raise RuntimeError("synthetic circuit-store failure")

    def record_success(self, route):  # type: ignore[no-untyped-def]
        del route
        raise RuntimeError("synthetic circuit-store failure")

    def record_failure(self, route):  # type: ignore[no-untyped-def]
        del route
        raise RuntimeError("synthetic circuit-store failure")


class MutableClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 22, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _policy(repository=None) -> AIPolicyEngine:
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=repository or StaticAIPolicyRepository(),
        deployment_enabled=True,
    )


def _gateway(
    provider: FakeAIProvider,
    *,
    availability: AIAvailabilityService,
    policy: AIPolicyEngine | None = None,
) -> AIGateway:
    route = build_test_model_route()
    return AIGateway(
        registry=build_task_registry(),
        policy=policy or _policy(),
        router=AIModelRouter(
            {route.alias: route},
            approved_provider_models=frozenset({route.provider_model}),
        ),
        providers={AIProviderName.OPENROUTER: provider},
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
        availability=availability,
    )


def _request() -> AIExecutionRequest:
    return AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text="Synthetic availability test."),
    )


@pytest.mark.asyncio
async def test_provider_disablement_blocks_before_provider_invocation() -> None:
    provider = FakeAIProvider()
    availability = AIAvailabilityService(
        controls=StaticAIProviderControlRepository({AIProviderName.OPENROUTER: False})
    )

    result = await _gateway(provider, availability=availability).execute(
        context=trusted_ai_context(), request=_request()
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PROVIDER_DISABLED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_runtime_global_switch_can_disable_and_reenable_without_restart() -> None:
    repository = MutablePolicyRepository()
    provider = FakeAIProvider()
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(),
        policy=_policy(repository),
    )

    repository.global_enabled = False
    disabled = await gateway.execute(context=trusted_ai_context(), request=_request())
    repository.global_enabled = True
    restored = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert disabled.error is not None
    assert disabled.error.category is AIErrorCategory.GATEWAY_DISABLED
    assert restored.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_runtime_provider_switch_can_disable_and_reenable_without_restart() -> None:
    controls = MutableProviderControlRepository(enabled=False)
    provider = FakeAIProvider()
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(controls=controls),
    )

    disabled = await gateway.execute(context=trusted_ai_context(), request=_request())
    controls.enabled = True
    restored = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert disabled.error is not None
    assert disabled.error.category is AIErrorCategory.PROVIDER_DISABLED
    assert restored.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_one_disabled_task_does_not_disable_an_unrelated_task() -> None:
    provider = FakeAIProvider()
    standard_route = build_test_model_route()
    protected_route = replace(
        standard_route,
        alias=AIModelAlias.PROTECTED_GENERAL_V1,
        provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
        model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
        approved_sensitivities=frozenset({SensitivityLevel.SENSITIVE}),
    )
    gateway = AIGateway(
        registry=build_task_registry(),
        policy=_policy(TaskAwarePolicyRepository()),
        router=AIModelRouter(
            {
                standard_route.alias: standard_route,
                protected_route.alias: protected_route,
            },
            approved_provider_models=frozenset({standard_route.provider_model}),
        ),
        providers={AIProviderName.OPENROUTER: provider},
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
        availability=AIAvailabilityService(),
    )

    disabled = await gateway.execute(
        context=trusted_ai_context(
            sensitivity=SensitivityLevel.SENSITIVE,
            permission=Permission.FILE_READ,
        ),
        request=AIExecutionRequest(
            task=AITaskType.PREPARE_WORK_NOTE,
            input_data=PrepareWorkNoteInput(note="Synthetic work note."),
        ),
    )
    allowed = await gateway.execute(
        context=trusted_ai_context(),
        request=_request(),
    )

    assert disabled.error is not None
    assert disabled.error.category is AIErrorCategory.TASK_DISABLED
    assert allowed.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_qualifying_failures_open_circuit_and_stop_provider_invocation() -> None:
    provider = FailingProvider()
    circuit = InMemoryAICircuitBreaker(
        AICircuitSettings(failure_threshold=2, failure_window_seconds=60)
    )
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(circuit=circuit),
    )

    first = await gateway.execute(context=trusted_ai_context(), request=_request())
    second = await gateway.execute(context=trusted_ai_context(), request=_request())
    blocked = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert first.error is not None and first.error.category is AIErrorCategory.PROVIDER_UNAVAILABLE
    assert (
        second.error is not None and second.error.category is AIErrorCategory.PROVIDER_UNAVAILABLE
    )
    assert blocked.error is not None and blocked.error.category is AIErrorCategory.CIRCUIT_OPEN
    assert blocked.error.retryable is True
    assert len(provider.requests) == 2


def test_half_open_allows_only_one_concurrent_probe() -> None:
    clock = MutableClock()
    route = build_test_model_route()
    circuit = InMemoryAICircuitBreaker(
        AICircuitSettings(failure_threshold=1, open_seconds=5, probe_lease_seconds=10),
        clock=clock,
    )
    assert circuit.before_call(route).allowed
    circuit.record_failure(route)
    clock.now += timedelta(seconds=6)

    with ThreadPoolExecutor(max_workers=8) as executor:
        permits = list(executor.map(lambda _: circuit.before_call(route), range(8)))

    assert sum(permit.allowed for permit in permits) == 1


def test_circuit_exact_threshold_and_complete_recovery_transition() -> None:
    clock = MutableClock()
    route = build_test_model_route()
    circuit = InMemoryAICircuitBreaker(
        AICircuitSettings(
            failure_threshold=3,
            failure_window_seconds=60,
            open_seconds=5,
            half_open_success_threshold=2,
            probe_lease_seconds=10,
        ),
        clock=clock,
    )

    circuit.record_failure(route)
    circuit.record_failure(route)
    assert circuit.peek(route).state is AICircuitState.CLOSED
    assert circuit.peek(route).allowed is True

    circuit.record_failure(route)
    assert circuit.peek(route).state is AICircuitState.OPEN
    assert circuit.before_call(route).allowed is False

    clock.now += timedelta(seconds=6)
    first_probe = circuit.before_call(route)
    assert first_probe.allowed is True
    assert first_probe.state is AICircuitState.HALF_OPEN
    circuit.record_success(route)
    assert circuit.peek(route).state is AICircuitState.HALF_OPEN

    second_probe = circuit.before_call(route)
    assert second_probe.allowed is True
    assert second_probe.state is AICircuitState.HALF_OPEN
    circuit.record_success(route)
    assert circuit.peek(route).state is AICircuitState.CLOSED


def test_failed_half_open_probe_reopens_and_later_recovers() -> None:
    clock = MutableClock()
    route = build_test_model_route()
    circuit = InMemoryAICircuitBreaker(
        AICircuitSettings(
            failure_threshold=1,
            open_seconds=5,
            half_open_success_threshold=1,
        ),
        clock=clock,
    )

    circuit.record_failure(route)
    clock.now += timedelta(seconds=6)
    assert circuit.before_call(route).state is AICircuitState.HALF_OPEN
    circuit.record_failure(route)
    assert circuit.peek(route).state is AICircuitState.OPEN
    assert circuit.before_call(route).allowed is False

    clock.now += timedelta(seconds=6)
    assert circuit.before_call(route).state is AICircuitState.HALF_OPEN
    circuit.record_success(route)
    assert circuit.peek(route).state is AICircuitState.CLOSED


@pytest.mark.parametrize(
    "category",
    [
        AIErrorCategory.PROVIDER_UNAVAILABLE,
        AIErrorCategory.TIMEOUT,
        AIErrorCategory.RATE_LIMITED,
        AIErrorCategory.PROVIDER_RESPONSE_INVALID,
        AIErrorCategory.STRUCTURED_OUTPUT_INVALID,
    ],
)
def test_only_documented_provider_failures_trip_the_circuit(
    category: AIErrorCategory,
) -> None:
    route = build_test_model_route()
    availability = AIAvailabilityService(
        circuit=InMemoryAICircuitBreaker(AICircuitSettings(failure_threshold=1))
    )

    assert availability.record_failure(route, category) is True
    decision = availability.evaluate_provider(route, acquire_probe=True)

    assert decision.allowed is False
    assert decision.reason is AIAvailabilityReason.CIRCUIT_OPEN


@pytest.mark.parametrize(
    "category",
    sorted(
        set(AIErrorCategory)
        - {
            AIErrorCategory.PROVIDER_UNAVAILABLE,
            AIErrorCategory.TIMEOUT,
            AIErrorCategory.RATE_LIMITED,
            AIErrorCategory.PROVIDER_RESPONSE_INVALID,
            AIErrorCategory.STRUCTURED_OUTPUT_INVALID,
        },
        key=lambda item: item.value,
    ),
)
def test_non_provider_rejections_do_not_poison_provider_health(
    category: AIErrorCategory,
) -> None:
    route = build_test_model_route()
    availability = AIAvailabilityService(
        circuit=InMemoryAICircuitBreaker(AICircuitSettings(failure_threshold=1))
    )

    assert availability.record_failure(route, category) is True
    decision = availability.evaluate_provider(route, acquire_probe=True)

    assert decision.allowed is True
    assert decision.reason is AIAvailabilityReason.AVAILABLE


@pytest.mark.parametrize(
    "availability",
    [
        AIAvailabilityService(controls=ExplodingProviderControlRepository()),
        AIAvailabilityService(circuit=ExplodingCircuit()),
    ],
)
@pytest.mark.asyncio
async def test_availability_control_plane_failures_fail_closed_before_provider_io(
    availability: AIAvailabilityService,
) -> None:
    provider = FakeAIProvider()

    result = await _gateway(provider, availability=availability).execute(
        context=trusted_ai_context(), request=_request()
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.CONFIGURATION_ERROR
    assert provider.requests == []


@pytest.mark.asyncio
async def test_kill_switch_activated_in_flight_discards_provider_result() -> None:
    repository = MutablePolicyRepository()
    provider = DisablingProvider(repository)
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(),
        policy=_policy(repository),
    )

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert result.result is None
    assert result.error is not None
    assert result.error.category is AIErrorCategory.RESULT_AUTHORITY_REVOKED
    assert len(provider.requests) == 1


def test_capability_check_never_invokes_provider() -> None:
    provider = FakeAIProvider()
    gateway = _gateway(provider, availability=AIAvailabilityService())

    capability = gateway.capability(
        context=trusted_ai_context(),
        task_type=AITaskType.SYNTHETIC_TEXT_SUMMARY,
    )

    assert capability.available is True
    assert provider.requests == []


@pytest.mark.asyncio
async def test_non_provider_rejection_does_not_trip_circuit() -> None:
    provider = FakeAIProvider()
    circuit = InMemoryAICircuitBreaker(AICircuitSettings(failure_threshold=1))
    repository = MutablePolicyRepository()
    repository.task_enabled = False
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(circuit=circuit),
        policy=_policy(repository),
    )

    denied = await gateway.execute(context=trusted_ai_context(), request=_request())
    repository.task_enabled = True
    allowed = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert denied.error is not None
    assert denied.error.category is AIErrorCategory.TASK_DISABLED
    assert allowed.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1
