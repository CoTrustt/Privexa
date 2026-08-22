from __future__ import annotations

import asyncio
from decimal import Decimal
from enum import StrEnum
from uuid import UUID, uuid4

from privexa_api.access_control.context import (
    ClientContext,
    _create_client_authorization_context,
)
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission
from privexa_api.ai_gateway.contracts import (
    AIFinishReason,
    AIModelAlias,
    AIUsage,
)
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.providers.base import (
    AIProviderMetadata,
    AIProviderRequest,
    AIProviderResult,
)
from privexa_api.ai_gateway.routing import AIModelRoute, AIProviderName
from privexa_api.ai_policy.contracts import (
    AIFallbackPolicy,
    AIModelClass,
    AIProviderClass,
)
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.execution_context import (
    ExecutionContext,
    TraceId,
    issue_execution_context,
)


def trusted_ai_context(
    *,
    sensitivity: SensitivityLevel = SensitivityLevel.STANDARD,
    permission: Permission = Permission.CLIENT_READ,
    user_id: UUID | None = None,
    membership_id: UUID | None = None,
    firm_id: UUID | None = None,
    client_id: UUID | None = None,
    request_id: UUID | None = None,
    trace_id: TraceId | None = None,
) -> ExecutionContext:
    authorization = _create_client_authorization_context(
        client_context=ClientContext(
            user_id=user_id or uuid4(),
            membership_id=membership_id or uuid4(),
            firm_id=firm_id or uuid4(),
            client_id=client_id or uuid4(),
            role=FirmRole.FIRM_OWNER,
        ),
        permission=permission,
    )
    return issue_execution_context(
        authorization=authorization,
        request_id=request_id or uuid4(),
        trace_id=trace_id,
        effective_sensitivity=sensitivity,
        originating_channel=OriginatingChannel.WEB,
    )


def build_test_model_route() -> AIModelRoute:
    return AIModelRoute(
        alias=AIModelAlias.FAST_GENERAL_V1,
        provider=AIProviderName.OPENROUTER,
        provider_model="test/provider-model",
        max_prompt_price_per_million_tokens=Decimal("1.00"),
        max_completion_price_per_million_tokens=Decimal("5.00"),
        provider_classes=frozenset(
            {
                AIProviderClass.ENTERPRISE_APPROVED,
                AIProviderClass.ZDR_APPROVED,
            }
        ),
        model_classes=frozenset({AIModelClass.GENERAL_APPROVED}),
        supports_zdr=True,
        approved_sensitivities=frozenset({SensitivityLevel.STANDARD}),
        supported_fallback_policies=frozenset({AIFallbackPolicy.NO_FALLBACK}),
    )


def build_test_policy_engine(*, enabled: bool = True) -> AIPolicyEngine:
    registry = build_policy_registry()
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(registry),
        repository=StaticAIPolicyRepository(),
        deployment_enabled=enabled,
    )


class FakeAIProvider:
    def __init__(
        self,
        *,
        output_text: str = '{"summary":"A concise synthetic summary."}',
        usage: AIUsage | None = None,
    ) -> None:
        self.output_text = output_text
        self.usage = usage
        self.requests: list[AIProviderRequest] = []
        self.closed = False

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.requests.append(request)
        return AIProviderResult(
            output_text=self.output_text,
            finish_reason=AIFinishReason.COMPLETED,
            usage=self.usage,
            metadata=AIProviderMetadata(
                provider="TEST_PROVIDER",
                model=request.route.provider_model,
                request_id="provider-request-test",
            ),
        )

    async def aclose(self) -> None:
        self.closed = True


class FakeProviderBehavior(StrEnum):
    SUCCESS = "SUCCESS"
    TIMEOUT = "TIMEOUT"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    HTTP_429 = "HTTP_429"
    HTTP_500 = "HTTP_500"
    HTTP_502 = "HTTP_502"
    HTTP_503 = "HTTP_503"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    SLOW_RESPONSE = "SLOW_RESPONSE"
    REPEATED_FAILURE = "REPEATED_FAILURE"
    FAIL_THEN_RECOVER = "FAIL_THEN_RECOVER"


class ScriptedAIProvider(FakeAIProvider):
    """Deterministic provider double for availability and race-condition tests."""

    def __init__(
        self,
        *behaviors: FakeProviderBehavior,
        started: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
    ) -> None:
        super().__init__()
        self.behaviors = behaviors or (FakeProviderBehavior.SUCCESS,)
        self.started = started
        self.release = release

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.behaviors) - 1)
        behavior = self.behaviors[index]
        if behavior is FakeProviderBehavior.SLOW_RESPONSE:
            if self.started is not None:
                self.started.set()
            if self.release is not None:
                await self.release.wait()
            return await self._success(request)
        if behavior is FakeProviderBehavior.MALFORMED_RESPONSE:
            return AIProviderResult(
                output_text="not-json",
                finish_reason=AIFinishReason.COMPLETED,
                metadata=AIProviderMetadata(
                    provider="TEST_PROVIDER",
                    model=request.route.provider_model,
                    request_id="provider-request-malformed",
                ),
            )
        if behavior is FakeProviderBehavior.FAIL_THEN_RECOVER and len(self.requests) > 1:
            return await self._success(request)
        if behavior is FakeProviderBehavior.SUCCESS:
            return await self._success(request)
        category = {
            FakeProviderBehavior.TIMEOUT: AIErrorCategory.TIMEOUT,
            FakeProviderBehavior.CONNECTION_FAILURE: AIErrorCategory.PROVIDER_UNAVAILABLE,
            FakeProviderBehavior.HTTP_429: AIErrorCategory.RATE_LIMITED,
            FakeProviderBehavior.HTTP_500: AIErrorCategory.PROVIDER_UNAVAILABLE,
            FakeProviderBehavior.HTTP_502: AIErrorCategory.PROVIDER_UNAVAILABLE,
            FakeProviderBehavior.HTTP_503: AIErrorCategory.PROVIDER_UNAVAILABLE,
            FakeProviderBehavior.REPEATED_FAILURE: AIErrorCategory.PROVIDER_UNAVAILABLE,
            FakeProviderBehavior.FAIL_THEN_RECOVER: AIErrorCategory.PROVIDER_UNAVAILABLE,
        }[behavior]
        raise ProviderFailure(category=category, retryable=True)

    async def _success(self, request: AIProviderRequest) -> AIProviderResult:
        return AIProviderResult(
            output_text=self.output_text,
            finish_reason=AIFinishReason.COMPLETED,
            usage=self.usage,
            metadata=AIProviderMetadata(
                provider="TEST_PROVIDER",
                model=request.route.provider_model,
                request_id="provider-request-test",
            ),
        )


class NoopAIProvenanceRecorder:
    """Explicit test double; production never disables provenance."""

    def start_execution(self, **_: object) -> None:
        return None

    def record_policy(self, **_: object) -> None:
        return None

    def record_protection(self, **_: object) -> None:
        return None

    def record_route(self, **_: object) -> None:
        return None

    def start_attempt(self, **_: object) -> None:
        return None

    def finish_attempt_success(self, **_: object) -> None:
        return None

    def finish_attempt_failure(self, **_: object) -> None:
        return None

    def finalize_execution(self, **_: object) -> None:
        return None


NOOP_AI_PROVENANCE = NoopAIProvenanceRecorder()
