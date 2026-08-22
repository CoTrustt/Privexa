from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from privexa_api.ai_gateway.contracts import AIFinishReason, AIUsage
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.providers.base import (
    AIProviderMetadata,
    AIProviderRequest,
    AIProviderResult,
)
from privexa_api.ai_policy.contracts import AIFallbackPolicy, ZDRRequirement

_OPENROUTER_COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
_PROVIDER_NAME = "OPENROUTER"


class _OpenRouterMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str | None = None


class _OpenRouterChoice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: _OpenRouterMessage
    finish_reason: str | None = None


class _OpenRouterTokenDetails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cached_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)


class _OpenRouterUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    prompt_tokens_details: _OpenRouterTokenDetails | None = None
    completion_tokens_details: _OpenRouterTokenDetails | None = None
    cost: Decimal | None = Field(default=None, ge=0)


class _OpenRouterErrorMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error_type: str | None = None


class _OpenRouterError(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: int | str | None = None
    message: str | None = None
    metadata: _OpenRouterErrorMetadata | None = None


class _OpenRouterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    model: str | None = None
    provider: str | None = None
    choices: list[_OpenRouterChoice] = Field(default_factory=list)
    usage: _OpenRouterUsage | None = None
    error: _OpenRouterError | None = None


class OpenRouterProvider:
    def __init__(
        self,
        *,
        api_key: SecretStr,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            follow_redirects=False,
        )

    async def execute(self, request: AIProviderRequest) -> AIProviderResult:
        payload = self._payload(request)
        try:
            response = await self._client.post(
                _OPENROUTER_COMPLETIONS_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=httpx.Timeout(request.timeout_seconds),
            )
        except httpx.TimeoutException as error:
            raise ProviderFailure(
                category=AIErrorCategory.TIMEOUT,
                retryable=True,
            ) from error
        except httpx.NetworkError as error:
            raise ProviderFailure(
                category=AIErrorCategory.PROVIDER_UNAVAILABLE,
                retryable=True,
            ) from error

        request_id = response.headers.get("x-request-id")
        retry_after = _retry_after_seconds(response)
        try:
            body: Any = response.json()
        except ValueError as error:
            category, retryable = _invalid_body_mapping(response.status_code)
            raise ProviderFailure(
                category=category,
                retryable=retryable,
                provider_http_status=response.status_code,
                provider_request_id=request_id,
            ) from error

        try:
            parsed = _OpenRouterResponse.model_validate(body)
        except ValidationError as error:
            category, retryable = _invalid_body_mapping(response.status_code)
            raise ProviderFailure(
                category=category,
                retryable=retryable,
                provider_http_status=response.status_code,
                provider_request_id=request_id,
            ) from error

        if response.is_error or parsed.error is not None:
            raise _provider_failure(
                status_code=response.status_code,
                error=parsed.error,
                request_id=request_id or parsed.id,
                retry_after_seconds=retry_after,
            )
        if not parsed.choices or parsed.choices[0].message.content is None:
            raise ProviderFailure(
                category=AIErrorCategory.PROVIDER_RESPONSE_INVALID,
                provider_http_status=response.status_code,
                provider_request_id=request_id or parsed.id,
            )

        content = parsed.choices[0].message.content.strip()
        if not content:
            raise ProviderFailure(
                category=AIErrorCategory.PROVIDER_RESPONSE_INVALID,
                provider_http_status=response.status_code,
                provider_request_id=request_id or parsed.id,
            )
        return AIProviderResult(
            output_text=content,
            finish_reason=_finish_reason(parsed.choices[0].finish_reason),
            usage=_usage(parsed.usage),
            metadata=AIProviderMetadata(
                provider=parsed.provider or _PROVIDER_NAME,
                adapter="OPENROUTER_CHAT_COMPLETIONS_V1",
                model=parsed.model or request.route.provider_model,
                request_id=request_id or parsed.id,
            ),
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _payload(request: AIProviderRequest) -> dict[str, object]:
        if request.controls.fallback_policy is not AIFallbackPolicy.NO_FALLBACK:
            raise ProviderFailure(category=AIErrorCategory.CONFIGURATION_ERROR)
        return {
            "model": request.route.provider_model,
            "messages": [message.model_dump(mode="json") for message in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": 0,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_schema_name,
                    "strict": True,
                    "schema": request.output_json_schema,
                },
            },
            "provider": {
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": request.controls.zdr_requirement is ZDRRequirement.REQUIRED,
                "max_price": {
                    "prompt": str(request.route.max_prompt_price_per_million_tokens),
                    "completion": str(request.route.max_completion_price_per_million_tokens),
                },
            },
        }


def _usage(value: _OpenRouterUsage | None) -> AIUsage | None:
    if value is None:
        return None
    prompt_details = value.prompt_tokens_details
    completion_details = value.completion_tokens_details
    return AIUsage(
        prompt_tokens=value.prompt_tokens,
        completion_tokens=value.completion_tokens,
        total_tokens=value.total_tokens,
        cached_tokens=prompt_details.cached_tokens if prompt_details is not None else None,
        reasoning_tokens=(
            completion_details.reasoning_tokens if completion_details is not None else None
        ),
        reported_cost=value.cost,
        cost_currency="USD" if value.cost is not None else None,
    )


def _finish_reason(value: str | None) -> AIFinishReason:
    return {
        "stop": AIFinishReason.COMPLETED,
        "length": AIFinishReason.LENGTH_LIMIT,
        "content_filter": AIFinishReason.CONTENT_FILTERED,
        "refusal": AIFinishReason.REFUSED,
        "error": AIFinishReason.ERROR,
    }.get(value or "", AIFinishReason.UNKNOWN)


def _retry_after_seconds(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if 1 <= value <= 3600 else None


def _provider_failure(
    *,
    status_code: int,
    error: _OpenRouterError | None,
    request_id: str | None,
    retry_after_seconds: int | None,
) -> ProviderFailure:
    error_type = error.metadata.error_type if error is not None and error.metadata else None
    effective_status = status_code
    if status_code < 400 and error is not None and isinstance(error.code, int):
        effective_status = error.code
    category, retryable = _error_mapping(effective_status, error_type)
    return ProviderFailure(
        category=category,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds if retryable else None,
        provider_http_status=status_code,
        provider_error_category=error_type,
        provider_request_id=request_id,
    )


def _invalid_body_mapping(status_code: int) -> tuple[AIErrorCategory, bool]:
    if status_code >= 400:
        return _error_mapping(status_code, None)
    return AIErrorCategory.PROVIDER_RESPONSE_INVALID, False


def _error_mapping(status_code: int, error_type: str | None) -> tuple[AIErrorCategory, bool]:
    if error_type in {"context_length_exceeded", "max_tokens_exceeded", "token_limit_exceeded"}:
        return AIErrorCategory.CONTEXT_LIMIT_EXCEEDED, False
    if error_type in {"content_policy_violation", "refusal"}:
        return AIErrorCategory.CONTENT_POLICY_DENIED, False
    if error_type == "rate_limit_exceeded" or status_code == 429:
        return AIErrorCategory.RATE_LIMITED, True
    if error_type == "timeout" or status_code in {408, 504}:
        return AIErrorCategory.TIMEOUT, True
    if error_type in {"provider_overloaded", "provider_unavailable", "server", "unmapped"}:
        return AIErrorCategory.PROVIDER_UNAVAILABLE, True
    if status_code == 401:
        return AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR, False
    if status_code == 402 or error_type == "payment_required":
        return AIErrorCategory.PROVIDER_CREDIT_EXHAUSTED, False
    if status_code == 403:
        return AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR, False
    if status_code >= 500:
        return AIErrorCategory.PROVIDER_UNAVAILABLE, True
    if status_code in {400, 404, 412, 413, 422}:
        return AIErrorCategory.CONFIGURATION_ERROR, False
    return AIErrorCategory.PROVIDER_RESPONSE_INVALID, False
