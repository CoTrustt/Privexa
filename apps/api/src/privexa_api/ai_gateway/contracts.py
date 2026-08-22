from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from privexa_api.ai_gateway.errors import AIError
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel

MAX_AI_SOURCE_REFERENCES = 100


class AIModelAlias(StrEnum):
    FAST_GENERAL_V1 = "FAST_GENERAL_V1"
    PROTECTED_GENERAL_V1 = "PROTECTED_GENERAL_V1"


class AIExecutionStatus(StrEnum):
    SUCCEEDED = "SUCCEEDED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class AIFinishReason(StrEnum):
    COMPLETED = "COMPLETED"
    LENGTH_LIMIT = "LENGTH_LIMIT"
    CONTENT_FILTERED = "CONTENT_FILTERED"
    REFUSED = "REFUSED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class AISourceReference(BaseModel):
    """Opaque source identity resolved server-side; never proof of authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    source_id: UUID


class AIInvocationMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    workflow_id: UUID | None = None
    parent_execution_id: UUID | None = None


class AIConstraintOverrides(BaseModel):
    """Caller limits can only tighten the authoritative task/platform constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    max_output_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)


class AIExecutionRequest(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    task: AITaskType
    input_data: BaseModel = Field(repr=False)
    source_references: tuple[AISourceReference, ...] = Field(
        default=(),
        max_length=MAX_AI_SOURCE_REFERENCES,
    )
    constraint_overrides: AIConstraintOverrides | None = None
    metadata: AIInvocationMetadata = Field(default_factory=AIInvocationMetadata)


class AIUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    reported_cost: Decimal | None = Field(default=None, ge=0)
    cost_currency: str | None = Field(
        default=None,
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
    )

    @model_validator(mode="after")
    def validate_cost_pair(self) -> AIUsage:
        if (self.reported_cost is None) != (self.cost_currency is None):
            raise ValueError("reported cost and currency must be supplied together")
        return self


class AIModelExecutionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    model_alias: AIModelAlias | None = None
    provider: str | None = Field(default=None, max_length=64)
    provider_model: str | None = Field(default=None, max_length=255)
    provider_request_id: str | None = Field(default=None, max_length=255)
    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)
    retry_count: int = Field(default=0, ge=0)
    policy_decision_id: UUID | None = None
    policy_version: str | None = Field(default=None, max_length=128)


class AIExecutionResult[ResultType: BaseModel](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    execution_id: UUID
    task: AITaskType | None
    task_version: str | None = Field(default=None, max_length=32)
    status: AIExecutionStatus
    result: ResultType | None = None
    error: AIError | None = None
    usage: AIUsage | None = None
    execution: AIModelExecutionMetadata
    finish_reason: AIFinishReason | None = None
    output_sensitivity: SensitivityLevel | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> AIExecutionResult[ResultType]:
        if self.status is AIExecutionStatus.SUCCEEDED:
            if self.task is None or self.result is None or self.error is not None:
                raise ValueError("successful AI execution requires a task, result, and no error")
        elif self.result is not None or self.error is None:
            raise ValueError("unsuccessful AI execution requires an error and no result")
        return self
