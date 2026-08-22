from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from privexa_api.ai_gateway.contracts import AIFinishReason, AIUsage
from privexa_api.ai_gateway.routing import AIModelRoute
from privexa_api.ai_policy.contracts import AIFallbackPolicy, ZDRRequirement


class AIProviderExecutionControls(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    policy_decision_id: UUID
    policy_version: str = Field(min_length=1, max_length=128)
    zdr_requirement: ZDRRequirement
    fallback_policy: AIFallbackPolicy
    max_cost_usd: Decimal = Field(gt=0)


class AIMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"


class AIProviderMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    role: AIMessageRole
    content: str = Field(min_length=1, repr=False)


class AIProviderRequest(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    route: AIModelRoute
    controls: AIProviderExecutionControls
    messages: tuple[AIProviderMessage, ...] = Field(min_length=2)
    output_schema_name: str = Field(min_length=1, max_length=64)
    output_json_schema: dict[str, object]
    max_output_tokens: int = Field(ge=1)
    timeout_seconds: float = Field(gt=0)


class AIProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    provider: str = Field(min_length=1, max_length=64)
    adapter: str = Field(default="UNKNOWN", min_length=1, max_length=128)
    model: str = Field(min_length=1, max_length=255)
    request_id: str | None = Field(default=None, max_length=255)


class AIProviderResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    output_text: str = Field(min_length=1, repr=False)
    finish_reason: AIFinishReason
    usage: AIUsage | None = None
    metadata: AIProviderMetadata


class AIProvider(Protocol):
    async def execute(self, request: AIProviderRequest) -> AIProviderResult: ...

    async def aclose(self) -> None: ...
