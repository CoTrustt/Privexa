from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from fixtures.ai_gateway import (
    NOOP_AI_PROVENANCE,
    FakeAIProvider,
    build_test_model_route,
    trusted_ai_context,
)
from pydantic import ValidationError

from privexa_api.ai_gateway.contracts import (
    AIConstraintOverrides,
    AIExecutionRequest,
    AIExecutionStatus,
    AIModelAlias,
    AISourceReference,
)
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.gateway import (
    AIGateway,
    _conservative_input_token_upper_bound,
    _worst_case_cost,
)
from privexa_api.ai_gateway.providers.base import (
    AIMessageRole,
    AIProviderMessage,
    AIProviderRequest,
)
from privexa_api.ai_gateway.routing import AIModelRoute, AIModelRouter, AIProviderName
from privexa_api.ai_gateway.tasks import (
    SYNTHETIC_TEXT_SUMMARY_TASK,
    AITaskRegistry,
    SyntheticTextSummaryInput,
    build_task_registry,
)
from privexa_api.ai_gateway.telemetry import AIExecutionTelemetry
from privexa_api.ai_policy.contracts import (
    AgentAuthority,
    AIFallbackPolicy,
    AIModelClass,
    AIPolicyConstraints,
    AIPolicyRule,
    AIProtectionProfileId,
    AIProviderClass,
    RedactionRequirement,
)
from privexa_api.ai_policy.errors import InvalidAIPolicyConfiguration
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_protection.contracts import (
    ProtectionAction,
    ProtectionEntitySummary,
    ProtectionResult,
)
from privexa_api.ai_protection.service import AIProtection
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel

pytestmark = pytest.mark.security


def _rule(
    constraints: AIPolicyConstraints, *, rule_id: str = "test.gateway.override"
) -> AIPolicyRule:
    payload = constraints.model_dump(mode="json", exclude_none=True)
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AIPolicyRule(
        rule_id=rule_id,
        revision=1,
        constraints=constraints,
        content_hash=content_hash,
    )


def _policy(
    *,
    constraints: AIPolicyConstraints | None = None,
    global_enabled: bool = True,
    task_enabled: bool = True,
    repository: object | None = None,
) -> AIPolicyEngine:
    policy_repository = repository or StaticAIPolicyRepository(
        global_enabled=global_enabled,
        task_enabled=task_enabled,
        override_rules=(_rule(constraints),) if constraints is not None else (),
    )
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=policy_repository,  # type: ignore[arg-type]
        deployment_enabled=True,
    )


class CountingRouter:
    def __init__(self, route: AIModelRoute, *, approved: bool = True) -> None:
        self.calls = 0
        self._delegate = AIModelRouter(
            {route.alias: route},
            approved_provider_models=(
                frozenset({route.provider_model}) if approved else frozenset()
            ),
        )

    def resolve(self, *args: object, **kwargs: object) -> AIModelRoute:
        self.calls += 1
        return self._delegate.resolve(*args, **kwargs)  # type: ignore[arg-type]


def _gateway(
    provider: FakeAIProvider,
    *,
    policy: AIPolicyEngine | None = None,
    route: AIModelRoute | None = None,
    registry: AITaskRegistry | None = None,
    protection: AIProtection | None = None,
) -> tuple[AIGateway, CountingRouter]:
    selected_route = route or build_test_model_route()
    router = CountingRouter(selected_route)
    gateway = AIGateway(
        registry=registry or build_task_registry(),
        policy=policy,  # type: ignore[arg-type]
        router=router,  # type: ignore[arg-type]
        providers={AIProviderName.OPENROUTER: provider},
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
        protection=protection,
    )
    return gateway, router


class FixedProtection:
    def protect(self, **kwargs: object) -> ProtectionResult:
        return ProtectionResult(
            protected_content="Contact <EMAIL_ADDRESS_001>",
            profile_id=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
            protection_applied=True,
            entity_summaries=(
                ProtectionEntitySummary(
                    entity_type="EMAIL_ADDRESS",
                    count=1,
                    action=ProtectionAction.TOKENIZE,
                ),
            ),
            duration_ms=1,
        )


def _request(
    *,
    text: str = "Synthetic policy boundary input.",
    max_output_tokens: int | None = None,
) -> AIExecutionRequest:
    overrides = (
        AIConstraintOverrides(max_output_tokens=max_output_tokens)
        if max_output_tokens is not None
        else None
    )
    return AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text=text),
        constraint_overrides=overrides,
    )


def _input_token_upper_bound(text: str) -> int:
    task = SYNTHETIC_TEXT_SUMMARY_TASK
    return _conservative_input_token_upper_bound(
        (
            AIProviderMessage(
                role=AIMessageRole.SYSTEM,
                content=task.prompt.system_instruction,
            ),
            AIProviderMessage(role=AIMessageRole.USER, content=text),
        ),
        task.output_model.model_json_schema(),
    )


@pytest.mark.asyncio
async def test_unknown_task_denies_before_router_and_provider_invocation() -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(provider, policy=_policy())
    request = AIExecutionRequest.model_construct(
        task=cast(AITaskType, "attacker_defined_task"),
        input_data=SyntheticTextSummaryInput(text="synthetic"),
        source_references=(),
        constraint_overrides=None,
        metadata=None,
    )

    result = await gateway.execute(context=trusted_ai_context(), request=request)

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.UNSUPPORTED_TASK
    assert router.calls == 0
    assert provider.requests == []


@pytest.mark.asyncio
async def test_missing_applicable_rule_denies_before_router_and_provider() -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(provider, policy=_policy())

    result = await gateway.execute(
        context=trusted_ai_context(sensitivity=SensitivityLevel.RESTRICTED),
        request=_request(),
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.POLICY_DENIED
    assert router.calls == 0
    assert provider.requests == []


class InvalidRepository:
    def load(self, *args: object, **kwargs: object) -> object:
        raise InvalidAIPolicyConfiguration("malformed authoritative policy")

    def validate_startup(self, *args: object, **kwargs: object) -> None:
        raise InvalidAIPolicyConfiguration("malformed authoritative policy")


class UnavailableRepository:
    def load(self, *args: object, **kwargs: object) -> object:
        raise RuntimeError("policy database unavailable")

    def validate_startup(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("policy database unavailable")


@pytest.mark.parametrize(
    ("repository", "expected_status", "expected_category"),
    [
        (InvalidRepository(), AIExecutionStatus.REJECTED, AIErrorCategory.POLICY_DENIED),
        (UnavailableRepository(), AIExecutionStatus.FAILED, AIErrorCategory.INTERNAL_ERROR),
    ],
)
@pytest.mark.asyncio
async def test_policy_configuration_or_infrastructure_failure_stops_execution(
    repository: object,
    expected_status: AIExecutionStatus,
    expected_category: AIErrorCategory,
) -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(provider, policy=_policy(repository=repository))

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is expected_status
    assert result.error is not None
    assert result.error.category is expected_category
    assert router.calls == 0
    assert provider.requests == []


@pytest.mark.parametrize(
    ("global_enabled", "task_enabled", "expected_category"),
    [
        (False, True, AIErrorCategory.GATEWAY_DISABLED),
        (True, False, AIErrorCategory.TASK_DISABLED),
    ],
)
@pytest.mark.asyncio
async def test_every_runtime_kill_switch_denies_before_route_selection(
    global_enabled: bool,
    task_enabled: bool,
    expected_category: AIErrorCategory,
) -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(
        provider,
        policy=_policy(global_enabled=global_enabled, task_enabled=task_enabled),
    )

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is expected_category
    assert router.calls == 0
    assert provider.requests == []


@pytest.mark.parametrize(
    "authority",
    [
        AgentAuthority.AUTHORITATIVE_DATABASE_MUTATION,
        AgentAuthority.EXTERNAL_COMMUNICATION,
        AgentAuthority.APPROVAL,
        AgentAuthority.SIGN_OFF,
        AgentAuthority.CROSS_CLIENT_DATA_MOVEMENT,
        AgentAuthority.DESTRUCTIVE_ACTION,
        AgentAuthority.PERMISSION_CHANGE,
    ],
)
@pytest.mark.asyncio
async def test_dangerous_authority_denies_through_real_gateway_without_provider_call(
    authority: AgentAuthority,
) -> None:
    provider = FakeAIProvider()
    dangerous_task = replace(
        SYNTHETIC_TEXT_SUMMARY_TASK,
        requested_agent_authorities=frozenset({AgentAuthority.READ_AUTHORISED_CONTEXT, authority}),
    )
    registry = AITaskRegistry({AITaskType.SYNTHETIC_TEXT_SUMMARY: dangerous_task})
    gateway, router = _gateway(provider, policy=_policy(), registry=registry)

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.POLICY_DENIED
    assert router.calls == 0
    assert provider.requests == []


@pytest.mark.parametrize(
    "route",
    [
        replace(
            build_test_model_route(),
            provider_classes=frozenset({AIProviderClass.INTERNAL_ONLY}),
        ),
        replace(
            build_test_model_route(),
            model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
        ),
    ],
)
@pytest.mark.asyncio
async def test_nonpermitted_provider_or_model_class_never_reaches_adapter(
    route: AIModelRoute,
) -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(provider, policy=_policy(), route=route)

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.NO_COMPLIANT_ROUTE
    assert router.calls == 1
    assert provider.requests == []


@pytest.mark.asyncio
async def test_zdr_required_policy_rejects_non_zdr_route_without_provider_call() -> None:
    provider = FakeAIProvider()
    non_zdr_route = replace(build_test_model_route(), supports_zdr=False)
    gateway, router = _gateway(provider, policy=_policy(), route=non_zdr_route)

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.NO_COMPLIANT_ROUTE
    assert router.calls == 1
    assert provider.requests == []


@pytest.mark.asyncio
async def test_redaction_required_policy_fails_closed_without_protection_before_routing() -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(
        provider,
        policy=_policy(
            constraints=AIPolicyConstraints(
                redaction_requirement=RedactionRequirement.REQUIRED,
                protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
            )
        ),
    )

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PII_PROTECTION_FAILED
    assert router.calls == 0
    assert provider.requests == []


@pytest.mark.asyncio
async def test_provider_request_receives_only_policy_protected_user_content() -> None:
    provider = FakeAIProvider()
    raw_content = "Contact raw-person@example.com"
    gateway, router = _gateway(
        provider,
        policy=_policy(
            constraints=AIPolicyConstraints(
                redaction_requirement=RedactionRequirement.REQUIRED,
                protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
            )
        ),
        protection=FixedProtection(),
    )

    result = await gateway.execute(
        context=trusted_ai_context(),
        request=_request(text=raw_content),
    )

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert router.calls == 1
    assert len(provider.requests) == 1
    user_messages = [
        message.content
        for message in provider.requests[0].messages
        if message.role is AIMessageRole.USER
    ]
    assert user_messages == ["Contact <EMAIL_ADDRESS_001>"]
    assert all(raw_content not in message.content for message in provider.requests[0].messages)


@pytest.mark.parametrize("untrusted_field", ["redacted", "supports_zdr", "policy_decision"])
def test_caller_cannot_assert_policy_or_provider_capabilities(untrusted_field: str) -> None:
    with pytest.raises(ValidationError):
        AIExecutionRequest.model_validate(
            {
                "task": AITaskType.SYNTHETIC_TEXT_SUMMARY,
                "input_data": SyntheticTextSummaryInput(text="synthetic"),
                untrusted_field: True,
            }
        )


@pytest.mark.parametrize(
    ("ceiling_delta", "expected_status", "expected_calls"),
    [
        (1, AIExecutionStatus.SUCCEEDED, 1),
        (0, AIExecutionStatus.SUCCEEDED, 1),
        (-1, AIExecutionStatus.REJECTED, 0),
    ],
)
@pytest.mark.asyncio
async def test_input_token_ceiling_exact_boundaries(
    ceiling_delta: int,
    expected_status: AIExecutionStatus,
    expected_calls: int,
) -> None:
    text = "Exact input token boundary."
    ceiling = _input_token_upper_bound(text) + ceiling_delta
    provider = FakeAIProvider()
    gateway, _ = _gateway(
        provider,
        policy=_policy(constraints=AIPolicyConstraints(max_input_tokens=ceiling)),
    )

    result = await gateway.execute(context=trusted_ai_context(), request=_request(text=text))

    assert result.status is expected_status
    assert len(provider.requests) == expected_calls


@pytest.mark.parametrize(
    ("requested", "expected_status", "expected_calls"),
    [
        (127, AIExecutionStatus.SUCCEEDED, 1),
        (128, AIExecutionStatus.SUCCEEDED, 1),
        (129, AIExecutionStatus.REJECTED, 0),
    ],
)
@pytest.mark.asyncio
async def test_output_token_ceiling_exact_boundaries_and_adapter_parameter(
    requested: int,
    expected_status: AIExecutionStatus,
    expected_calls: int,
) -> None:
    provider = FakeAIProvider()
    gateway, _ = _gateway(provider, policy=_policy())

    result = await gateway.execute(
        context=trusted_ai_context(),
        request=_request(max_output_tokens=requested),
    )

    assert result.status is expected_status
    assert len(provider.requests) == expected_calls
    if provider.requests:
        assert provider.requests[0].max_output_tokens == requested


@pytest.mark.asyncio
async def test_omitted_output_limit_becomes_explicit_policy_safe_adapter_limit() -> None:
    provider = FakeAIProvider()
    gateway, _ = _gateway(provider, policy=_policy())

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert provider.requests[0].max_output_tokens == 128


@pytest.mark.parametrize(
    ("ceiling_delta", "expected_status", "expected_calls"),
    [
        (Decimal("0.000000001"), AIExecutionStatus.SUCCEEDED, 1),
        (Decimal("0"), AIExecutionStatus.SUCCEEDED, 1),
        (Decimal("-0.000000001"), AIExecutionStatus.REJECTED, 0),
    ],
)
@pytest.mark.asyncio
async def test_worst_case_decimal_cost_ceiling_exact_boundaries(
    ceiling_delta: Decimal,
    expected_status: AIExecutionStatus,
    expected_calls: int,
) -> None:
    text = "Exact cost boundary."
    route = build_test_model_route()
    estimated = _worst_case_cost(
        route=route,
        input_tokens=_input_token_upper_bound(text),
        output_tokens=128,
    )
    provider = FakeAIProvider()
    gateway, _ = _gateway(
        provider,
        policy=_policy(constraints=AIPolicyConstraints(max_cost_usd=estimated + ceiling_delta)),
        route=route,
    )

    result = await gateway.execute(context=trusted_ai_context(), request=_request(text=text))

    assert result.status is expected_status
    assert len(provider.requests) == expected_calls


def test_missing_or_zero_pricing_metadata_is_rejected_at_route_configuration() -> None:
    with pytest.raises(ValueError, match="capability metadata is incomplete"):
        replace(
            build_test_model_route(),
            max_prompt_price_per_million_tokens=Decimal("0"),
        )


class FailingProvider(FakeAIProvider):
    async def execute(self, request: AIProviderRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        raise ProviderFailure(category=AIErrorCategory.PROVIDER_UNAVAILABLE, retryable=True)


@pytest.mark.asyncio
async def test_no_fallback_policy_performs_one_provider_attempt_only() -> None:
    provider = FailingProvider()
    gateway, _ = _gateway(provider, policy=_policy())

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.FAILED
    assert len(provider.requests) == 1
    assert provider.requests[0].controls.fallback_policy is AIFallbackPolicy.NO_FALLBACK


@pytest.mark.asyncio
async def test_route_without_no_fallback_support_is_rejected_before_provider() -> None:
    provider = FakeAIProvider()
    route = replace(
        build_test_model_route(),
        supported_fallback_policies=frozenset({AIFallbackPolicy.SAME_SECURITY_CLASS_ONLY}),
    )
    gateway, _ = _gateway(provider, policy=_policy(), route=route)

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.REJECTED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_cross_client_source_reference_cannot_be_laundered_into_execution() -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(provider, policy=_policy())
    request = AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text="synthetic"),
        source_references=(AISourceReference(source_type="evidence", source_id=uuid4()),),
    )

    result = await gateway.execute(context=trusted_ai_context(), request=request)

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.INVALID_INPUT
    assert router.calls == 0
    assert provider.requests == []


@pytest.mark.asyncio
async def test_missing_policy_dependency_fails_closed_without_provider_execution() -> None:
    provider = FakeAIProvider()
    gateway, router = _gateway(provider, policy=None)

    result = await gateway.execute(context=trusted_ai_context(), request=_request())

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.INTERNAL_ERROR
    assert router.calls == 0
    assert provider.requests == []


def test_execution_request_is_immutable_after_construction() -> None:
    request = _request()
    with pytest.raises(ValidationError):
        request.task = cast(AITaskType, "attacker_defined_task")
    with pytest.raises(ValidationError):
        request.constraint_overrides = AIConstraintOverrides(max_output_tokens=999)


def test_provider_route_cannot_be_constructed_with_unapproved_empty_capability_metadata() -> None:
    with pytest.raises(ValueError, match="capability metadata is incomplete"):
        AIModelRoute(
            alias=AIModelAlias.FAST_GENERAL_V1,
            provider=AIProviderName.OPENROUTER,
            provider_model="synthetic/model",
            max_prompt_price_per_million_tokens=Decimal("1"),
            max_completion_price_per_million_tokens=Decimal("1"),
            provider_classes=frozenset(),
            model_classes=frozenset({AIModelClass.GENERAL_APPROVED}),
            supports_zdr=True,
            approved_sensitivities=frozenset({SensitivityLevel.STANDARD}),
            supported_fallback_policies=frozenset({AIFallbackPolicy.NO_FALLBACK}),
        )
