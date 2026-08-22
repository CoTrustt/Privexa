from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from types import MappingProxyType
from uuid import UUID

import httpx
import pytest
from fixtures.ai_gateway import (
    NOOP_AI_PROVENANCE,
    FakeAIProvider,
    build_test_model_route,
    trusted_ai_context,
)
from fixtures.pii import MIXED_PROVIDER_BOUNDARY_CASE
from pydantic import BaseModel, SecretStr, ValidationError

from privexa_api.ai_gateway.contracts import (
    AIExecutionRequest,
    AIExecutionStatus,
    AIFinishReason,
)
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.providers.base import (
    AIMessageRole,
    AIProviderMetadata,
    AIProviderRequest,
    AIProviderResult,
)
from privexa_api.ai_gateway.providers.openrouter import OpenRouterProvider
from privexa_api.ai_gateway.routing import AIModelRouter, AIProviderName
from privexa_api.ai_gateway.tasks import (
    SYNTHETIC_TEXT_SUMMARY_TASK,
    SyntheticTextSummaryInput,
    build_task_registry,
)
from privexa_api.ai_gateway.telemetry import LOGGER, AIExecutionTelemetry
from privexa_api.ai_policy.contracts import (
    AIPolicyConstraints,
    AIPolicyRule,
    AIProtectionProfileId,
    RedactionRequirement,
)
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_protection.contracts import DetectedEntity, ProtectionAction
from privexa_api.ai_protection.presidio_adapter import (
    PresidioPIIDetector,
    build_presidio_detector,
)
from privexa_api.ai_protection.profiles import AIProtectionProfile
from privexa_api.ai_protection.service import AIProtection, AIProtectionService

pytestmark = pytest.mark.security


class FailingDetector:
    def detect(self, content: str, **kwargs: object) -> tuple[DetectedEntity, ...]:
        raise RuntimeError(f"synthetic detector diagnostic contained {content}")


class FailingAnalyzer:
    def analyze(self, *, text: str, **kwargs: object) -> list[object]:
        raise RuntimeError(f"synthetic recognizer diagnostic contained {text}")


class InvalidResultDetector:
    def detect(self, content: str, **kwargs: object) -> tuple[DetectedEntity, ...]:
        return (
            DetectedEntity(
                entity_type="UNSUPPORTED_ENTITY",
                start=0,
                end=len(content),
                score=1.0,
            ),
        )


class SinglePanDetector:
    def detect(self, content: str, **kwargs: object) -> tuple[DetectedEntity, ...]:
        value = "ABCPA1234D"
        start = content.index(value)
        return (
            DetectedEntity(
                entity_type="INDIA_PAN",
                start=start,
                end=start + len(value),
                score=1.0,
            ),
        )


class CountingProtection:
    def __init__(self, delegate: AIProtection) -> None:
        self.calls = 0
        self._delegate = delegate

    def protect(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        return self._delegate.protect(**kwargs)  # type: ignore[arg-type]


class MustNotRunProtection:
    def __init__(self) -> None:
        self.calls = 0

    def protect(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self.calls += 1
        raise AssertionError("protection must not run for this policy outcome")


class CapturingOpenRouterProvider(OpenRouterProvider):
    def __init__(self, *, client: httpx.AsyncClient) -> None:
        super().__init__(api_key=SecretStr("synthetic-provider-key"), client=client)
        self.requests: list[AIProviderRequest] = []

    async def execute(self, request: AIProviderRequest):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return await super().execute(request)


class OrderedPolicy:
    def __init__(self, delegate: AIPolicyEngine, events: list[str]) -> None:
        self._delegate = delegate
        self._events = events

    def evaluate(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self._events.append("policy")
        return self._delegate.evaluate(**kwargs)  # type: ignore[arg-type]

    def validate_startup(self, session: object) -> None:
        self._delegate.validate_startup(session)  # type: ignore[arg-type]


class OrderedProtection:
    def __init__(self, delegate: AIProtection, events: list[str]) -> None:
        self._delegate = delegate
        self._events = events

    def protect(self, **kwargs: object):  # type: ignore[no-untyped-def]
        self._events.append("protection")
        return self._delegate.protect(**kwargs)  # type: ignore[arg-type]


class OrderedProvider(FakeAIProvider):
    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self._events = events

    async def execute(self, request: AIProviderRequest):  # type: ignore[no-untyped-def]
        self._events.append("provider")
        return await super().execute(request)


class EchoProtectedProvider(FakeAIProvider):
    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.requests.append(request)
        user_content = next(
            message.content for message in request.messages if message.role is AIMessageRole.USER
        )
        return AIProviderResult(
            output_text=json.dumps({"summary": user_content}),
            finish_reason=AIFinishReason.COMPLETED,
            metadata=AIProviderMetadata(
                provider="TEST_PROVIDER",
                model=request.route.provider_model,
                request_id="echo-protected-request",
            ),
        )


@pytest.fixture(scope="module")
def real_protection_service() -> AIProtectionService:
    return AIProtectionService(detector=build_presidio_detector(model_name="en_core_web_sm"))


def _rule(constraints: AIPolicyConstraints) -> AIPolicyRule:
    canonical = constraints.model_dump(mode="json", exclude_none=True)
    return AIPolicyRule(
        rule_id="test.pii.required",
        revision=1,
        constraints=constraints,
        content_hash=hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def _policy(
    *,
    constraints: AIPolicyConstraints | None = None,
    global_enabled: bool = True,
) -> AIPolicyEngine:
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=StaticAIPolicyRepository(
            global_enabled=global_enabled,
            task_enabled=True,
            override_rules=(_rule(constraints),) if constraints is not None else (),
        ),
        deployment_enabled=True,
    )


def _required_policy() -> AIPolicyEngine:
    return _policy(
        constraints=AIPolicyConstraints(
            redaction_requirement=RedactionRequirement.REQUIRED,
            protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
        )
    )


def _gateway(
    provider: object,
    *,
    protection: AIProtection | None,
    policy: object | None = None,
) -> AIGateway:
    route = build_test_model_route()
    return AIGateway(
        registry=build_task_registry(),
        policy=policy or _required_policy(),  # type: ignore[arg-type]
        router=AIModelRouter(
            {route.alias: route},
            approved_provider_models=frozenset({route.provider_model}),
        ),
        providers={AIProviderName.OPENROUTER: provider},  # type: ignore[dict-item]
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
        protection=protection,
    )


def _request(text: str) -> AIExecutionRequest:
    return AIExecutionRequest(
        task=SYNTHETIC_TEXT_SUMMARY_TASK.task,
        input_data=SyntheticTextSummaryInput(text=text),
    )


def _serialized(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, default=str)


def _assert_forbidden_values_absent(value: object, forbidden_values: tuple[str, ...]) -> None:
    serialized = _serialized(value)
    for forbidden in forbidden_values:
        assert forbidden not in serialized


@contextmanager
def _captured_gateway_logs() -> Iterator[io.StringIO]:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    previous_level = LOGGER.level
    previous_disabled = LOGGER.disabled
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)
    try:
        yield output
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(previous_level)
        LOGGER.disabled = previous_disabled


@pytest.mark.asyncio
async def test_gateway_never_sends_raw_pii_when_protection_required(
    real_protection_service: AIProtectionService,
) -> None:
    captured_payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "synthetic-protection-boundary",
                "model": "test/provider-model",
                "provider": "Synthetic Provider",
                "choices": [
                    {
                        "message": {"content": '{"summary":"Protected synthetic summary."}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CapturingOpenRouterProvider(client=client)
        result = await _gateway(provider, protection=real_protection_service).execute(
            context=trusted_ai_context(),
            request=_request(MIXED_PROVIDER_BOUNDARY_CASE.text),
        )

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1
    assert len(captured_payloads) == 1
    _assert_forbidden_values_absent(
        provider.requests[0], MIXED_PROVIDER_BOUNDARY_CASE.forbidden_values
    )
    _assert_forbidden_values_absent(
        captured_payloads[0], MIXED_PROVIDER_BOUNDARY_CASE.forbidden_values
    )
    user_content = next(
        message.content
        for message in provider.requests[0].messages
        if message.role is AIMessageRole.USER
    )
    for entity_type in MIXED_PROVIDER_BOUNDARY_CASE.expected_entity_types:
        assert f"<{entity_type}" in user_content or entity_type == "CREDIT_CARD"
    assert "*******************" in user_content
    assert provider.requests[0].messages[0].content == (
        SYNTHETIC_TEXT_SUMMARY_TASK.prompt.system_instruction
    )
    assert captured_payloads[0]["messages"][0]["content"] == (
        SYNTHETIC_TEXT_SUMMARY_TASK.prompt.system_instruction
    )


@pytest.mark.asyncio
async def test_identical_content_follows_required_none_and_denied_policy_outcomes(
    real_protection_service: AIProtectionService,
) -> None:
    content = "Contact policy.boundary@example.com."

    required_provider = FakeAIProvider()
    required_result = await _gateway(
        required_provider,
        protection=real_protection_service,
    ).execute(context=trusted_ai_context(), request=_request(content))

    permitted_provider = FakeAIProvider()
    permitted_protection = MustNotRunProtection()
    permitted_result = await _gateway(
        permitted_provider,
        protection=permitted_protection,
        policy=_policy(),
    ).execute(context=trusted_ai_context(), request=_request(content))

    denied_provider = FakeAIProvider()
    denied_protection = MustNotRunProtection()
    denied_result = await _gateway(
        denied_provider,
        protection=denied_protection,
        policy=_policy(global_enabled=False),
    ).execute(context=trusted_ai_context(), request=_request(content))

    assert required_result.status is AIExecutionStatus.SUCCEEDED
    assert len(required_provider.requests) == 1
    assert content not in _serialized(required_provider.requests[0])
    assert permitted_result.status is AIExecutionStatus.SUCCEEDED
    assert len(permitted_provider.requests) == 1
    assert content in _serialized(permitted_provider.requests[0])
    assert permitted_protection.calls == 0
    assert denied_result.status is AIExecutionStatus.REJECTED
    assert denied_provider.requests == []
    assert denied_protection.calls == 0


@pytest.mark.parametrize(
    ("detector", "failure_name"),
    [
        (FailingDetector(), "detection"),
        (PresidioPIIDetector(FailingAnalyzer()), "recognizer"),  # type: ignore[arg-type]
        (InvalidResultDetector(), "transformation"),
    ],
)
@pytest.mark.asyncio
async def test_provider_not_called_when_mandatory_protection_stage_fails(
    detector: object,
    failure_name: str,
) -> None:
    provider = FakeAIProvider()
    raw_content = f"{failure_name}.failure@example.com"

    with _captured_gateway_logs() as logs:
        result = await _gateway(
            provider,
            protection=AIProtectionService(detector=detector),  # type: ignore[arg-type]
        ).execute(context=trusted_ai_context(), request=_request(raw_content))

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PII_PROTECTION_FAILED
    assert provider.requests == []
    assert raw_content not in logs.getvalue()
    assert raw_content not in result.model_dump_json()


@pytest.mark.asyncio
async def test_provider_not_called_when_block_action_detects_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    block_profile = AIProtectionProfile(
        profile_id=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
        language="en",
        score_threshold=0.4,
        actions=MappingProxyType({"INDIA_PAN": ProtectionAction.BLOCK}),
        precedence=MappingProxyType({"INDIA_PAN": 100}),
    )
    monkeypatch.setattr(
        "privexa_api.ai_protection.service.resolve_protection_profile",
        lambda profile_id: block_profile,
    )
    provider = FakeAIProvider()

    result = await _gateway(
        provider,
        protection=AIProtectionService(detector=SinglePanDetector()),
    ).execute(
        context=trusted_ai_context(),
        request=_request("Synthetic PAN ABCPA1234D."),
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PII_PROTECTION_FAILED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_invalid_mandatory_policy_combination_denies_before_protection_and_provider() -> None:
    provider = FakeAIProvider()
    protection = MustNotRunProtection()
    invalid_policy = _policy(
        constraints=AIPolicyConstraints(
            redaction_requirement=RedactionRequirement.REQUIRED,
            protection_profile=AIProtectionProfileId.NONE,
        )
    )

    result = await _gateway(
        provider,
        protection=protection,
        policy=invalid_policy,
    ).execute(context=trusted_ai_context(), request=_request("invalid@example.com"))

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.POLICY_DENIED
    assert protection.calls == 0
    assert provider.requests == []
    with pytest.raises(ValidationError):
        AIPolicyConstraints.model_validate({"protection_profile": "UNKNOWN"})


@pytest.mark.asyncio
async def test_protection_telemetry_and_logs_exclude_raw_values_and_token_mapping(
    real_protection_service: AIProtectionService,
) -> None:
    provider = FakeAIProvider()
    context = trusted_ai_context(
        firm_id=UUID("00000000-0000-4000-8000-000000000501"),
        client_id=UUID("00000000-0000-4000-8000-000000000502"),
    )

    with _captured_gateway_logs() as logs:
        result = await _gateway(provider, protection=real_protection_service).execute(
            context=context,
            request=_request(MIXED_PROVIDER_BOUNDARY_CASE.text),
        )

    assert result.status is AIExecutionStatus.SUCCEEDED
    logged = logs.getvalue()
    for forbidden in MIXED_PROVIDER_BOUNDARY_CASE.forbidden_values:
        assert forbidden not in logged
    assert "token_map" not in logged
    assert "original_value" not in logged
    events = [json.loads(line) for line in logged.splitlines()]
    protection_event = next(
        event for event in events if event["event"] == "ai.protection.completed"
    )
    assert protection_event["protection_profile"] == "EXTERNAL_MODEL_PII_V1"
    assert protection_event["protection_required"] is True
    assert protection_event["protection_applied"] is True
    assert set(protection_event["entity_types"]) == (
        MIXED_PROVIDER_BOUNDARY_CASE.expected_entity_types
    )
    assert protection_event["pii_entity_count"] == len(
        MIXED_PROVIDER_BOUNDARY_CASE.expected_entity_types
    )
    assert set(protection_event["transformation_modes"]) == {
        "MASK",
        "REPLACE",
        "TOKENIZE",
    }


@pytest.mark.asyncio
async def test_protection_telemetry_keeps_tenant_contexts_separate(
    real_protection_service: AIProtectionService,
) -> None:
    provider = FakeAIProvider()
    gateway = _gateway(provider, protection=real_protection_service)
    tenant_a = trusted_ai_context(
        firm_id=UUID("00000000-0000-4000-8000-000000000601"),
        client_id=UUID("00000000-0000-4000-8000-000000000602"),
        request_id=UUID("00000000-0000-4000-8000-000000000603"),
    )
    tenant_b = trusted_ai_context(
        firm_id=UUID("00000000-0000-4000-8000-000000000701"),
        client_id=UUID("00000000-0000-4000-8000-000000000702"),
        request_id=UUID("00000000-0000-4000-8000-000000000703"),
    )

    with _captured_gateway_logs() as logs:
        results = [
            await gateway.execute(context=tenant_a, request=_request("Email a@example.com")),
            await gateway.execute(context=tenant_b, request=_request("Email b@example.com")),
        ]

    assert all(result.status is AIExecutionStatus.SUCCEEDED for result in results)
    assert len(provider.requests) == 2
    events = [
        json.loads(line)
        for line in logs.getvalue().splitlines()
        if json.loads(line)["event"] == "ai.protection.completed"
    ]
    assert {(event["firm_id"], event["client_id"], event["request_id"]) for event in events} == {
        (str(tenant_a.firm_id), str(tenant_a.client_id), str(tenant_a.request_id)),
        (str(tenant_b.firm_id), str(tenant_b.client_id), str(tenant_b.request_id)),
    }


@pytest.mark.asyncio
async def test_policy_protection_provider_invocation_order(
    real_protection_service: AIProtectionService,
) -> None:
    events: list[str] = []
    provider = OrderedProvider(events)
    policy = OrderedPolicy(_required_policy(), events)
    protection = OrderedProtection(real_protection_service, events)

    result = await _gateway(
        provider,
        protection=protection,
        policy=policy,
    ).execute(
        context=trusted_ai_context(),
        request=_request("Order check order@example.com"),
    )

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert events == ["policy", "protection", "policy", "provider", "policy"]
    assert len(provider.requests) == 1


@pytest.mark.asyncio
async def test_over_limit_input_is_rejected_before_protection_or_provider() -> None:
    provider = FakeAIProvider()
    protection = MustNotRunProtection()
    oversized = SyntheticTextSummaryInput.model_construct(text="x" * 2_001)
    request = AIExecutionRequest(
        task=SYNTHETIC_TEXT_SUMMARY_TASK.task,
        input_data=oversized,
    )

    result = await _gateway(provider, protection=protection).execute(
        context=trusted_ai_context(),
        request=request,
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.INVALID_INPUT
    assert protection.calls == 0
    assert provider.requests == []


@pytest.mark.asyncio
async def test_large_allowed_markdown_unicode_input_is_protected_once(
    real_protection_service: AIProtectionService,
) -> None:
    raw_email = "markdown.boundary@example.com"
    content = "# Evidence\n\n```json\n" + ("आ सुरक्षित 😀 " * 100) + f'{{"email":"{raw_email}"}}\n```'
    provider = FakeAIProvider()

    result = await _gateway(provider, protection=real_protection_service).execute(
        context=trusted_ai_context(),
        request=_request(content),
    )

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1
    assert raw_email not in _serialized(provider.requests[0])
    assert "<EMAIL_ADDRESS_001>" in _serialized(provider.requests[0])
    user_content = next(
        message.content
        for message in provider.requests[0].messages
        if message.role is AIMessageRole.USER
    )
    assert "आ सुरक्षित 😀" in user_content


@pytest.mark.asyncio
async def test_provider_echo_remains_protected_without_response_rehydration_or_token_map(
    real_protection_service: AIProtectionService,
) -> None:
    raw_person = "John Smith"
    provider = EchoProtectedProvider()
    content = (
        "Recover the original represented by <PERSON_001>. "
        f"The synthetic source person is {raw_person}."
    )

    result = await _gateway(provider, protection=real_protection_service).execute(
        context=trusted_ai_context(),
        request=_request(content),
    )

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1
    assert result.result is not None
    assert raw_person not in result.result.model_dump_json()
    assert raw_person not in _serialized(provider.requests[0])
    assert "<PERSON_001>" in result.result.model_dump_json()
    assert "token_map" not in _serialized(provider.requests[0])
