from __future__ import annotations

import asyncio
import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from fixtures.ai_gateway import (
    NOOP_AI_PROVENANCE,
    FakeAIProvider,
    build_test_model_route,
    build_test_policy_engine,
    trusted_ai_context,
)
from pydantic import SecretStr

from privexa_api.ai_gateway.contracts import (
    AIExecutionRequest,
    AIExecutionStatus,
    AIFinishReason,
    AITaskType,
    AIUsage,
)
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.providers.base import (
    AIProviderMetadata,
    AIProviderRequest,
    AIProviderResult,
)
from privexa_api.ai_gateway.providers.openrouter import OpenRouterProvider
from privexa_api.ai_gateway.routing import AIModelRouter, AIProviderName
from privexa_api.ai_gateway.tasks import SyntheticTextSummaryInput, build_task_registry
from privexa_api.ai_gateway.telemetry import LOGGER, AIExecutionTelemetry
from privexa_api.observability import metrics as ai_metrics
from privexa_api.security.enums import SensitivityLevel

USER_A = UUID("00000000-0000-4000-8000-000000000101")
MEMBERSHIP_A = UUID("00000000-0000-4000-8000-000000000102")
FIRM_A = UUID("00000000-0000-4000-8000-000000000103")
CLIENT_A = UUID("00000000-0000-4000-8000-000000000104")
REQUEST_A = UUID("00000000-0000-4000-8000-000000000105")
TRACE_A = "1234567890abcdef1234567890abcdef"

USER_B = UUID("00000000-0000-4000-8000-000000000201")
MEMBERSHIP_B = UUID("00000000-0000-4000-8000-000000000202")
FIRM_B = UUID("00000000-0000-4000-8000-000000000203")
CLIENT_B = UUID("00000000-0000-4000-8000-000000000204")
REQUEST_B = UUID("00000000-0000-4000-8000-000000000205")
TRACE_B = "abcdef1234567890abcdef1234567890"


def _gateway(provider) -> AIGateway:
    route = build_test_model_route()
    return AIGateway(
        registry=build_task_registry(),
        policy=build_test_policy_engine(),
        router=AIModelRouter(
            {route.alias: route},
            approved_provider_models=frozenset({route.provider_model}),
        ),
        providers={AIProviderName.OPENROUTER: provider},
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
    )


def _request(text: str) -> AIExecutionRequest:
    return AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text=text),
    )


@contextmanager
def _captured_ai_logs() -> Iterator[io.StringIO]:
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


def _json_events(logged: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in logged.splitlines() if line.startswith("{")]


class CapturingCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, amount: int, attributes: dict[str, str]) -> None:
        self.calls.append((amount, attributes))


def test_availability_metrics_use_only_bounded_non_tenant_dimensions(monkeypatch) -> None:
    counters = {
        name: CapturingCounter()
        for name in (
            "AI_GATEWAY_REQUESTS",
            "AI_GATEWAY_BLOCKED",
            "AI_PROVIDER_FAILURES",
            "AI_PROVIDER_TIMEOUTS",
            "AI_CIRCUIT_OPEN",
            "AI_RESULT_INTERRUPTION",
        )
    }
    for name, counter in counters.items():
        monkeypatch.setattr(ai_metrics, name, counter)

    ai_metrics.record_ai_event(
        "ai.execution.denied",
        {
            "task": "ai.prepare_work_note",
            "status": "REJECTED",
            "error_category": "CIRCUIT_OPEN",
            "provider": "OPENROUTER",
            "user_id": str(USER_A),
            "firm_id": str(FIRM_A),
            "client_id": str(CLIENT_A),
            "execution_id": str(REQUEST_A),
            "prompt_hash": "sensitive-high-cardinality-value",
        },
    )

    expected_attributes = {
        "ai.task_type": "ai.prepare_work_note",
        "ai.status": "REJECTED",
        "ai.failure_category": "CIRCUIT_OPEN",
        "ai.provider_class": "OPENROUTER",
    }
    assert counters["AI_GATEWAY_REQUESTS"].calls == [(1, expected_attributes)]
    assert counters["AI_GATEWAY_BLOCKED"].calls == [(1, expected_attributes)]
    assert counters["AI_CIRCUIT_OPEN"].calls == [(1, expected_attributes)]
    assert counters["AI_PROVIDER_FAILURES"].calls == []
    serialized = json.dumps(counters, default=lambda value: value.calls)
    for forbidden in (str(USER_A), str(FIRM_A), str(CLIENT_A), "sensitive-high-cardinality"):
        assert forbidden not in serialized


def test_provider_failure_timeout_and_interruption_metrics_are_exact(monkeypatch) -> None:
    counters = {
        name: CapturingCounter()
        for name in (
            "AI_GATEWAY_REQUESTS",
            "AI_GATEWAY_BLOCKED",
            "AI_PROVIDER_FAILURES",
            "AI_PROVIDER_TIMEOUTS",
            "AI_CIRCUIT_OPEN",
            "AI_RESULT_INTERRUPTION",
        )
    }
    for name, counter in counters.items():
        monkeypatch.setattr(ai_metrics, name, counter)

    ai_metrics.record_ai_event(
        "ai.execution.failed",
        {
            "task": "ai.prepare_work_note",
            "status": "FAILED",
            "error_category": "TIMEOUT",
            "provider": "OPENROUTER",
        },
    )
    ai_metrics.record_ai_event(
        "ai.execution.denied",
        {
            "task": "ai.prepare_work_note",
            "status": "REJECTED",
            "error_category": "RESULT_AUTHORITY_REVOKED",
            "provider": "OPENROUTER",
        },
    )

    assert len(counters["AI_GATEWAY_REQUESTS"].calls) == 2
    assert len(counters["AI_PROVIDER_FAILURES"].calls) == 1
    assert len(counters["AI_PROVIDER_TIMEOUTS"].calls) == 1
    assert len(counters["AI_GATEWAY_BLOCKED"].calls) == 1
    assert len(counters["AI_RESULT_INTERRUPTION"].calls) == 1
    assert counters["AI_CIRCUIT_OPEN"].calls == []
    for counter in counters.values():
        for _, attributes in counter.calls:
            assert set(attributes).issubset(
                {
                    "ai.task_type",
                    "ai.status",
                    "ai.failure_category",
                    "ai.provider_class",
                }
            )


@pytest.mark.asyncio
async def test_success_telemetry_has_attribution_without_content_or_raw_output() -> None:
    source_marker = "PRIVEXA_SECRET_TEST_PAYLOAD_918273"
    output_marker = "PRIVEXA_RAW_MODEL_OUTPUT_SECRET_7744"
    provider = FakeAIProvider(
        output_text=json.dumps({"summary": output_marker}),
        usage=AIUsage(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            reported_cost=Decimal("0.0042"),
            cost_currency="USD",
        ),
    )
    context = trusted_ai_context(
        user_id=USER_A,
        membership_id=MEMBERSHIP_A,
        firm_id=FIRM_A,
        client_id=CLIENT_A,
        request_id=REQUEST_A,
        trace_id=TRACE_A,
    )

    with _captured_ai_logs() as output:
        result = await _gateway(provider).execute(
            context=context,
            request=_request(source_marker),
        )

    assert result.status is AIExecutionStatus.SUCCEEDED
    logged = output.getvalue()
    events = _json_events(logged)
    assert [event["event"] for event in events] == [
        "ai.execution.started",
        "ai.execution.completed",
    ]
    assert {event["execution_id"] for event in events} == {str(result.execution_id)}
    completed = events[1]
    assert completed["principal_id"] == str(USER_A)
    assert completed["firm_id"] == str(FIRM_A)
    assert completed["client_id"] == str(CLIENT_A)
    assert completed["request_id"] == str(REQUEST_A)
    assert completed["trace_id"] == TRACE_A
    assert completed["sensitivity"] == SensitivityLevel.STANDARD.value
    assert completed["task"] == AITaskType.SYNTHETIC_TEXT_SUMMARY.value
    assert completed["task_version"] == "1"
    assert completed["provider"] == "TEST_PROVIDER"
    assert completed["provider_model"] == "test/provider-model"
    assert completed["prompt_tokens"] == 100
    assert completed["completion_tokens"] == 20
    assert completed["total_tokens"] == 120
    assert completed["reported_cost"] == "0.0042"
    assert completed["started_at"]
    assert completed["completed_at"]
    assert isinstance(completed["latency_ms"], int)
    assert source_marker not in logged
    assert output_marker not in logged
    assert "Authorization" not in logged
    assert "Bearer" not in logged


@pytest.mark.asyncio
async def test_structured_output_failure_logs_neither_source_nor_raw_model_content() -> None:
    source_marker = "STRUCTURED_FAILURE_SOURCE_SECRET_8844"
    raw_output_marker = "STRUCTURED_FAILURE_RAW_OUTPUT_SECRET_9955"
    provider = FakeAIProvider(output_text=raw_output_marker)

    with _captured_ai_logs() as output:
        result = await _gateway(provider).execute(
            context=trusted_ai_context(),
            request=_request(source_marker),
        )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.STRUCTURED_OUTPUT_INVALID
    logged = output.getvalue()
    assert "ai.execution.failed" in logged
    assert source_marker not in logged
    assert raw_output_marker not in logged


@pytest.mark.asyncio
async def test_real_adapter_success_and_failure_logs_exclude_key_header_body_and_source() -> None:
    api_key_marker = "PRIVEXA_TEST_KEY_SHOULD_NEVER_APPEAR"
    source_marker = "ADAPTER_LOG_SOURCE_SECRET_1166"
    provider_body_marker = "PROVIDER_INTERNAL_SECRET_12345"
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {"content": '{"summary":"safe"}'},
                            "finish_reason": "stop",
                        }
                    ]
                },
            )
        return httpx.Response(
            401,
            json={
                "error": {
                    "code": 401,
                    "message": provider_body_marker,
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr(api_key_marker), client=client)
        gateway = _gateway(provider)
        with _captured_ai_logs() as output:
            success = await gateway.execute(
                context=trusted_ai_context(),
                request=_request(source_marker),
            )
            failure = await gateway.execute(
                context=trusted_ai_context(),
                request=_request(source_marker),
            )

    assert success.status is AIExecutionStatus.SUCCEEDED
    assert failure.status is AIExecutionStatus.FAILED
    assert failure.error is not None
    assert failure.error.category is AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR
    logged = output.getvalue()
    assert api_key_marker not in logged
    assert source_marker not in logged
    assert provider_body_marker not in logged
    assert "Authorization" not in logged
    assert "Bearer" not in logged


@pytest.mark.asyncio
async def test_restricted_denial_logs_safe_metadata_without_source_content() -> None:
    source_marker = "RESTRICTED_SOURCE_MUST_NOT_BE_LOGGED_5511"
    provider = FakeAIProvider()
    context = trusted_ai_context(
        sensitivity=SensitivityLevel.RESTRICTED,
        firm_id=FIRM_A,
        client_id=CLIENT_A,
        request_id=REQUEST_A,
        trace_id=TRACE_A,
    )

    with _captured_ai_logs() as output:
        result = await _gateway(provider).execute(
            context=context,
            request=_request(source_marker),
        )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.POLICY_DENIED
    assert provider.requests == []
    logged = output.getvalue()
    events = _json_events(logged)
    assert len(events) == 1
    assert events[0]["event"] == "ai.execution.denied"
    assert events[0]["execution_id"] == str(result.execution_id)
    assert events[0]["sensitivity"] == SensitivityLevel.RESTRICTED.value
    assert source_marker not in logged


class UnexpectedFailureProvider(FakeAIProvider):
    def __init__(self, detail: str) -> None:
        super().__init__()
        self.detail = detail

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.requests.append(request)
        raise RuntimeError(self.detail)


@pytest.mark.asyncio
async def test_unexpected_exception_logging_is_sanitized() -> None:
    source_marker = "UNEXPECTED_FAILURE_SOURCE_SECRET_7733"
    exception_marker = "UNEXPECTED_EXCEPTION_SECRET_6622"
    provider = UnexpectedFailureProvider(exception_marker)

    with _captured_ai_logs() as output:
        result = await _gateway(provider).execute(
            context=trusted_ai_context(),
            request=_request(source_marker),
        )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.INTERNAL_ERROR
    logged = output.getvalue()
    assert "ai.execution.failed" in logged
    assert str(result.execution_id) in logged
    assert "exception_type" in logged
    assert exception_marker not in logged
    assert source_marker not in logged


class ContentAwareProvider:
    def __init__(self) -> None:
        self.requests: list[AIProviderRequest] = []

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        self.requests.append(request)
        await asyncio.sleep(0)
        source = request.messages[1].content
        return AIProviderResult(
            output_text=json.dumps({"summary": f"summary:{source}"}),
            finish_reason=AIFinishReason.COMPLETED,
            metadata=AIProviderMetadata(
                provider="SECOND_PROVIDER_FAKE",
                model=request.route.provider_model,
                request_id=f"provider:{source}",
            ),
        )

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_parallel_tenant_executions_keep_context_result_and_telemetry_isolated() -> None:
    provider = ContentAwareProvider()
    gateway = _gateway(provider)
    context_a = trusted_ai_context(
        user_id=USER_A,
        membership_id=MEMBERSHIP_A,
        firm_id=FIRM_A,
        client_id=CLIENT_A,
        request_id=REQUEST_A,
        trace_id=TRACE_A,
    )
    context_b = trusted_ai_context(
        user_id=USER_B,
        membership_id=MEMBERSHIP_B,
        firm_id=FIRM_B,
        client_id=CLIENT_B,
        request_id=REQUEST_B,
        trace_id=TRACE_B,
    )

    with _captured_ai_logs() as output:
        result_a, result_b = await asyncio.gather(
            gateway.execute(context=context_a, request=_request("tenant-a-source")),
            gateway.execute(context=context_b, request=_request("tenant-b-source")),
        )

    assert result_a.result is not None
    assert result_b.result is not None
    assert result_a.result.model_dump() == {"summary": "summary:tenant-a-source"}
    assert result_b.result.model_dump() == {"summary": "summary:tenant-b-source"}
    assert result_a.execution_id != result_b.execution_id
    assert len(provider.requests) == 2
    outbound = " ".join(
        message.content for request in provider.requests for message in request.messages
    )
    for identifier in (USER_A, FIRM_A, CLIENT_A, USER_B, FIRM_B, CLIENT_B):
        assert str(identifier) not in outbound

    events = _json_events(output.getvalue())
    by_execution: dict[str, list[dict[str, object]]] = {}
    for event in events:
        by_execution.setdefault(str(event["execution_id"]), []).append(event)
    assert set(by_execution) == {str(result_a.execution_id), str(result_b.execution_id)}
    assert {event["client_id"] for event in by_execution[str(result_a.execution_id)]} == {
        str(CLIENT_A)
    }
    assert {event["client_id"] for event in by_execution[str(result_b.execution_id)]} == {
        str(CLIENT_B)
    }
