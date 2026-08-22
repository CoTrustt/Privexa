from __future__ import annotations

import asyncio

import pytest
from fixtures.ai_gateway import (
    NOOP_AI_PROVENANCE,
    FakeAIProvider,
    FakeProviderBehavior,
    ScriptedAIProvider,
    build_test_model_route,
    trusted_ai_context,
)

from privexa_api.ai_gateway.availability import AIAvailabilityService
from privexa_api.ai_gateway.circuit_breaker import AICircuitSettings, InMemoryAICircuitBreaker
from privexa_api.ai_gateway.contracts import AIExecutionRequest, AIExecutionStatus
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.provider_controls import StaticAIProviderControlRepository
from privexa_api.ai_gateway.routing import AIModelRouter, AIProviderName
from privexa_api.ai_gateway.tasks import SyntheticTextSummaryInput, build_task_registry
from privexa_api.ai_gateway.telemetry import AIExecutionTelemetry
from privexa_api.ai_policy.contracts import AIPolicyRuntimeSnapshot
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel


class MutablePolicyRepository(StaticAIPolicyRepository):
    def __init__(self, *, global_enabled: bool = True, task_enabled: bool = True) -> None:
        self.global_enabled = global_enabled
        self.task_enabled = task_enabled

    def load(self, session, *, context, task, sensitivity) -> AIPolicyRuntimeSnapshot:
        return AIPolicyRuntimeSnapshot(
            global_enabled=self.global_enabled,
            task_enabled=self.task_enabled,
        )


class SequencedPolicyRepository(StaticAIPolicyRepository):
    def __init__(self, *global_states: bool) -> None:
        self.global_states = global_states
        self.calls = 0

    def load(self, session, *, context, task, sensitivity) -> AIPolicyRuntimeSnapshot:
        index = min(self.calls, len(self.global_states) - 1)
        self.calls += 1
        return AIPolicyRuntimeSnapshot(
            global_enabled=self.global_states[index],
            task_enabled=True,
        )


class ExplodingPolicyRepository(StaticAIPolicyRepository):
    def load(self, session, *, context, task, sensitivity) -> AIPolicyRuntimeSnapshot:
        raise RuntimeError("synthetic policy-store failure")


class MutableProviderControls:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def is_enabled(self, provider: AIProviderName) -> bool:
        assert provider is AIProviderName.OPENROUTER
        return self.enabled


class ProviderDisablingRouter(AIModelRouter):
    def __init__(self, controls: MutableProviderControls) -> None:
        route = build_test_model_route()
        super().__init__(
            {route.alias: route},
            approved_provider_models=frozenset({route.provider_model}),
        )
        self.controls = controls

    def resolve(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        route = super().resolve(*args, **kwargs)
        self.controls.enabled = False
        return route


def _policy(repository: StaticAIPolicyRepository) -> AIPolicyEngine:
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=repository,
        deployment_enabled=True,
    )


def _gateway(
    primary: FakeAIProvider,
    *,
    policy_repository: StaticAIPolicyRepository | None = None,
    availability: AIAvailabilityService | None = None,
    secondary: FakeAIProvider | None = None,
    router: AIModelRouter | None = None,
) -> AIGateway:
    route = build_test_model_route()
    providers = {AIProviderName.OPENROUTER: primary}
    if secondary is not None:
        providers[AIProviderName.DETERMINISTIC] = secondary
    return AIGateway(
        registry=build_task_registry(),
        policy=_policy(policy_repository or StaticAIPolicyRepository()),
        router=router
        or AIModelRouter(
            {route.alias: route},
            approved_provider_models=frozenset({route.provider_model}),
        ),
        providers=providers,
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
        availability=availability or AIAvailabilityService(),
    )


def _request() -> AIExecutionRequest:
    return AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text="Synthetic adversarial request."),
    )


@pytest.mark.parametrize(
    (
        "global_enabled",
        "task_enabled",
        "provider_enabled",
        "policy_allowed",
        "open_circuit",
        "expected",
    ),
    [
        (False, True, True, True, False, AIErrorCategory.GATEWAY_DISABLED),
        (True, False, True, True, False, AIErrorCategory.TASK_DISABLED),
        (True, True, False, True, False, AIErrorCategory.PROVIDER_DISABLED),
        (True, True, True, False, False, AIErrorCategory.POLICY_DENIED),
        (True, True, True, True, True, AIErrorCategory.CIRCUIT_OPEN),
        (True, True, True, True, False, None),
    ],
)
@pytest.mark.asyncio
async def test_control_precedence_matrix_never_widens_authority(
    global_enabled: bool,
    task_enabled: bool,
    provider_enabled: bool,
    policy_allowed: bool,
    open_circuit: bool,
    expected: AIErrorCategory | None,
) -> None:
    provider = FakeAIProvider()
    route = build_test_model_route()
    circuit = InMemoryAICircuitBreaker(AICircuitSettings(failure_threshold=1))
    if open_circuit:
        circuit.record_failure(route)
    gateway = _gateway(
        provider,
        policy_repository=MutablePolicyRepository(
            global_enabled=global_enabled,
            task_enabled=task_enabled,
        ),
        availability=AIAvailabilityService(
            controls=StaticAIProviderControlRepository(
                {AIProviderName.OPENROUTER: provider_enabled}
            ),
            circuit=circuit,
        ),
    )
    context = trusted_ai_context(
        sensitivity=SensitivityLevel.STANDARD if policy_allowed else SensitivityLevel.RESTRICTED
    )

    result = await gateway.execute(context=context, request=_request())

    if expected is None:
        assert result.status is AIExecutionStatus.SUCCEEDED
        assert len(provider.requests) == 1
    else:
        assert result.error is not None and result.error.category is expected
        assert result.usage is None
        assert provider.requests == []


@pytest.mark.asyncio
async def test_global_disable_blocks_every_configured_provider_and_any_second_attempt() -> None:
    primary = ScriptedAIProvider(FakeProviderBehavior.SUCCESS)
    secondary = FakeAIProvider()
    repository = MutablePolicyRepository(global_enabled=False)

    result = await _gateway(
        primary,
        secondary=secondary,
        policy_repository=repository,
    ).execute(context=trusted_ai_context(), request=_request())

    assert result.error is not None
    assert result.error.category is AIErrorCategory.GATEWAY_DISABLED
    assert result.usage is None
    assert primary.requests == []
    assert secondary.requests == []


@pytest.mark.parametrize(
    ("behavior", "category"),
    [
        (FakeProviderBehavior.TIMEOUT, AIErrorCategory.TIMEOUT),
        (FakeProviderBehavior.CONNECTION_FAILURE, AIErrorCategory.PROVIDER_UNAVAILABLE),
        (FakeProviderBehavior.HTTP_429, AIErrorCategory.RATE_LIMITED),
        (FakeProviderBehavior.HTTP_500, AIErrorCategory.PROVIDER_UNAVAILABLE),
        (FakeProviderBehavior.HTTP_502, AIErrorCategory.PROVIDER_UNAVAILABLE),
        (FakeProviderBehavior.HTTP_503, AIErrorCategory.PROVIDER_UNAVAILABLE),
        (FakeProviderBehavior.REPEATED_FAILURE, AIErrorCategory.PROVIDER_UNAVAILABLE),
    ],
)
@pytest.mark.asyncio
async def test_build_zero_provider_failures_have_one_bounded_attempt(
    behavior: FakeProviderBehavior,
    category: AIErrorCategory,
) -> None:
    primary = ScriptedAIProvider(behavior)
    secondary = FakeAIProvider()

    result = await _gateway(primary, secondary=secondary).execute(
        context=trusted_ai_context(), request=_request()
    )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None and result.error.category is category
    assert len(primary.requests) == 1
    assert secondary.requests == []


@pytest.mark.asyncio
async def test_malformed_provider_output_is_rejected_and_never_applied() -> None:
    provider = ScriptedAIProvider(FakeProviderBehavior.MALFORMED_RESPONSE)

    result = await _gateway(provider).execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.FAILED
    assert result.result is None
    assert result.error is not None
    assert result.error.category is AIErrorCategory.STRUCTURED_OUTPUT_INVALID
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_authority_is_rechecked_immediately_before_provider_io() -> None:
    provider = FakeAIProvider()
    repository = SequencedPolicyRepository(True, False)

    result = await _gateway(provider, policy_repository=repository).execute(
        context=trusted_ai_context(), request=_request()
    )

    assert repository.calls == 2
    assert result.error is not None
    assert result.error.category is AIErrorCategory.GATEWAY_DISABLED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_provider_disable_after_route_selection_blocks_invocation() -> None:
    controls = MutableProviderControls()
    provider = FakeAIProvider()
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(controls=controls),
        router=ProviderDisablingRouter(controls),
    )

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.error is not None
    assert result.error.category is AIErrorCategory.PROVIDER_DISABLED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_in_flight_shutdown_discards_result_using_deterministic_barrier() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    provider = ScriptedAIProvider(
        FakeProviderBehavior.SLOW_RESPONSE,
        started=started,
        release=release,
    )
    repository = MutablePolicyRepository()
    execution = asyncio.create_task(
        _gateway(provider, policy_repository=repository).execute(
            context=trusted_ai_context(), request=_request()
        )
    )
    await started.wait()
    repository.global_enabled = False
    release.set()

    result = await execution

    assert len(provider.requests) == 1
    assert result.status is AIExecutionStatus.REJECTED
    assert result.result is None
    assert result.error is not None
    assert result.error.category is AIErrorCategory.RESULT_AUTHORITY_REVOKED


@pytest.mark.asyncio
async def test_each_bounded_reasoning_step_rechecks_and_preserves_committed_state() -> None:
    repository = MutablePolicyRepository()
    provider = FakeAIProvider()
    gateway = _gateway(provider, policy_repository=repository)
    committed_deterministic_state: list[str] = []

    first_reasoning_step = await gateway.execute(context=trusted_ai_context(), request=_request())
    assert first_reasoning_step.status is AIExecutionStatus.SUCCEEDED
    committed_deterministic_state.append("valid deterministic operation")
    repository.global_enabled = False
    next_reasoning_step = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert next_reasoning_step.error is not None
    assert next_reasoning_step.error.category is AIErrorCategory.GATEWAY_DISABLED
    assert len(provider.requests) == 1
    assert committed_deterministic_state == ["valid deterministic operation"]


@pytest.mark.asyncio
async def test_policy_control_exception_fails_closed_before_provider_io() -> None:
    provider = FakeAIProvider()

    result = await _gateway(
        provider,
        policy_repository=ExplodingPolicyRepository(),
    ).execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.INTERNAL_ERROR
    assert provider.requests == []


@pytest.mark.asyncio
async def test_fail_then_recover_does_not_require_restart() -> None:
    provider = ScriptedAIProvider(
        FakeProviderBehavior.FAIL_THEN_RECOVER,
        FakeProviderBehavior.FAIL_THEN_RECOVER,
    )
    gateway = _gateway(
        provider,
        availability=AIAvailabilityService(
            circuit=InMemoryAICircuitBreaker(AICircuitSettings(failure_threshold=5))
        ),
    )

    failed = await gateway.execute(context=trusted_ai_context(), request=_request())
    recovered = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert failed.error is not None
    assert failed.error.category is AIErrorCategory.PROVIDER_UNAVAILABLE
    assert recovered.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 2
