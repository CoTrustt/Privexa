from __future__ import annotations

import json
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from fixtures.ai_gateway import build_test_model_route
from pydantic import SecretStr

from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.providers.base import (
    AIMessageRole,
    AIProviderExecutionControls,
    AIProviderMessage,
    AIProviderRequest,
)
from privexa_api.ai_gateway.providers.openrouter import OpenRouterProvider
from privexa_api.ai_policy.contracts import AIFallbackPolicy, ZDRRequirement


def _provider_request() -> AIProviderRequest:
    return AIProviderRequest(
        route=build_test_model_route(),
        controls=AIProviderExecutionControls(
            policy_decision_id=UUID("00000000-0000-4000-8000-000000000001"),
            policy_version="test-v1",
            zdr_requirement=ZDRRequirement.REQUIRED,
            fallback_policy=AIFallbackPolicy.NO_FALLBACK,
            max_cost_usd=Decimal("0.05"),
        ),
        messages=(
            AIProviderMessage(role=AIMessageRole.SYSTEM, content="Trusted instruction."),
            AIProviderMessage(role=AIMessageRole.USER, content="Untrusted synthetic text."),
        ),
        output_schema_name="synthetic_text_summary_v1",
        output_json_schema={
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
            "additionalProperties": False,
        },
        max_output_tokens=128,
        timeout_seconds=20.0,
    )


@pytest.mark.asyncio
async def test_openrouter_adapter_uses_private_structured_request_and_optional_usage() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "generation-test",
                "model": "test/provider-model",
                "provider": "Test Upstream",
                "choices": [
                    {
                        "message": {"content": '{"summary":"Synthetic summary."}'},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("secret-test-key"), client=client)
        result = await provider.execute(_provider_request())

    assert result.usage is None
    assert result.output_text == '{"summary":"Synthetic summary."}'
    assert captured["authorization"] == "Bearer secret-test-key"
    assert captured["method"] == "POST"
    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["max_tokens"] == 128
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["provider"]["zdr"] is True
    assert payload["provider"]["data_collection"] == "deny"
    assert payload["provider"]["allow_fallbacks"] is False


@pytest.mark.asyncio
async def test_openrouter_adapter_uses_fixed_endpoint_and_content_type() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content_type"] = request.headers.get("content-type")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"summary":"Synthetic summary."}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        await provider.execute(_provider_request())

    assert captured == {
        "method": "POST",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "content_type": "application/json",
    }


@pytest.mark.asyncio
async def test_openrouter_success_normalizes_usage_cost_and_ignores_extra_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "generation-usage",
                "model": "test/provider-model",
                "provider": "Test Upstream",
                "unrelated_future_field": {"safe": True},
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"Synthetic summary."}',
                            "future_message_field": "ignored",
                        },
                        "finish_reason": "stop",
                        "future_choice_field": "ignored",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cost": "0.0042",
                    "prompt_tokens_details": {"cached_tokens": 11},
                    "completion_tokens_details": {"reasoning_tokens": 3},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        result = await provider.execute(_provider_request())

    assert result.metadata.provider == "Test Upstream"
    assert result.metadata.model == "test/provider-model"
    assert result.metadata.request_id == "generation-usage"
    assert result.usage is not None
    assert result.usage.prompt_tokens == 100
    assert result.usage.completion_tokens == 20
    assert result.usage.total_tokens == 120
    assert result.usage.cached_tokens == 11
    assert result.usage.reasoning_tokens == 3
    assert result.usage.reported_cost == Decimal("0.0042")
    assert result.usage.cost_currency == "USD"


@pytest.mark.asyncio
async def test_openrouter_preserves_explicit_zero_cost() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"summary":"Synthetic summary."}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await OpenRouterProvider(
            api_key=SecretStr("test-openrouter-key"), client=client
        ).execute(_provider_request())

    assert result.usage is not None
    assert result.usage.reported_cost == Decimal("0")
    assert result.usage.cost_currency == "USD"


@pytest.mark.asyncio
async def test_openrouter_rate_limit_is_normalized_without_body_leakage() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "30", "X-Request-ID": "request-rate-limited"},
            json={
                "error": {
                    "code": 429,
                    "message": "provider-specific private message",
                    "metadata": {"error_type": "rate_limit_exceeded"},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("secret-test-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.RATE_LIMITED
    assert captured.value.retryable is True
    assert captured.value.retry_after_seconds == 30
    assert captured.value.provider_request_id == "request-rate-limited"
    assert "private message" not in str(captured.value)
    assert attempts == 1


@pytest.mark.asyncio
async def test_openrouter_invalid_json_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="not-json")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("secret-test-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.PROVIDER_UNAVAILABLE
    assert captured.value.retryable is True


@pytest.mark.asyncio
async def test_openrouter_invalid_success_json_is_provider_response_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="PROVIDER_RAW_BODY_MUST_NOT_LEAK")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.PROVIDER_RESPONSE_INVALID
    assert captured.value.retryable is False
    assert "PROVIDER_RAW_BODY_MUST_NOT_LEAK" not in str(captured.value)


@pytest.mark.asyncio
async def test_openrouter_structurally_invalid_success_response_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"unexpected": "shape"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.PROVIDER_RESPONSE_INVALID
    assert captured.value.retryable is False


@pytest.mark.asyncio
async def test_openrouter_malformed_usage_cost_fails_without_inventing_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": '{"summary":"Synthetic summary."}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"cost": "not-a-decimal"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.PROVIDER_RESPONSE_INVALID
    assert captured.value.retryable is False


@pytest.mark.parametrize(
    ("status_code", "expected_category", "expected_retryable"),
    [
        (400, AIErrorCategory.CONFIGURATION_ERROR, False),
        (401, AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR, False),
        (403, AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR, False),
        (500, AIErrorCategory.PROVIDER_UNAVAILABLE, True),
        (503, AIErrorCategory.PROVIDER_UNAVAILABLE, True),
    ],
)
@pytest.mark.asyncio
async def test_openrouter_http_errors_are_normalized_without_retries(
    status_code: int,
    expected_category: AIErrorCategory,
    expected_retryable: bool,
) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "code": status_code,
                    "message": "PROVIDER_INTERNAL_SECRET_12345",
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is expected_category
    assert captured.value.retryable is expected_retryable
    assert "PROVIDER_INTERNAL_SECRET_12345" not in str(captured.value)
    assert attempts == 1


@pytest.mark.asyncio
async def test_openrouter_context_limit_error_has_distinct_category() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "too large",
                    "metadata": {"error_type": "context_length_exceeded"},
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.CONTEXT_LIMIT_EXCEEDED
    assert captured.value.retryable is False


@pytest.mark.asyncio
async def test_openrouter_timeout_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.TIMEOUT
    assert captured.value.retryable is True
    assert "provider timeout detail" not in str(captured.value)


@pytest.mark.asyncio
async def test_openrouter_network_failure_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private DNS detail", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        with pytest.raises(ProviderFailure) as captured:
            await provider.execute(_provider_request())

    assert captured.value.category is AIErrorCategory.PROVIDER_UNAVAILABLE
    assert captured.value.retryable is True
    assert "private DNS detail" not in str(captured.value)


@pytest.mark.asyncio
async def test_injected_http_client_lifecycle_remains_owned_by_caller() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"), client=client)
        await provider.aclose()
        assert client.is_closed is False


@pytest.mark.asyncio
async def test_provider_closes_its_owned_reusable_http_client() -> None:
    provider = OpenRouterProvider(api_key=SecretStr("test-openrouter-key"))
    owned_client = provider._client

    await provider.aclose()

    assert owned_client.is_closed is True
