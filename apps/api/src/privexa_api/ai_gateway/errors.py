from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class AIErrorCategory(StrEnum):
    GATEWAY_DISABLED = "GATEWAY_DISABLED"
    TASK_DISABLED = "TASK_DISABLED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    RESULT_AUTHORITY_REVOKED = "RESULT_AUTHORITY_REVOKED"
    POLICY_DENIED = "POLICY_DENIED"
    NO_COMPLIANT_ROUTE = "NO_COMPLIANT_ROUTE"
    UNSUPPORTED_TASK = "UNSUPPORTED_TASK"
    INVALID_INPUT = "INVALID_INPUT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    PROVIDER_AUTHENTICATION_ERROR = "PROVIDER_AUTHENTICATION_ERROR"
    PROVIDER_CREDIT_EXHAUSTED = "PROVIDER_CREDIT_EXHAUSTED"
    RATE_LIMITED = "RATE_LIMITED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    CONTEXT_LIMIT_EXCEEDED = "CONTEXT_LIMIT_EXCEEDED"
    COST_LIMIT_EXCEEDED = "COST_LIMIT_EXCEEDED"
    STRUCTURED_OUTPUT_INVALID = "STRUCTURED_OUTPUT_INVALID"
    PROVIDER_RESPONSE_INVALID = "PROVIDER_RESPONSE_INVALID"
    CONTENT_POLICY_DENIED = "CONTENT_POLICY_DENIED"
    PII_PROTECTION_FAILED = "PII_PROTECTION_FAILED"
    CLIENT_BOUNDARY_VIOLATION = "CLIENT_BOUNDARY_VIOLATION"
    PROVENANCE_UNAVAILABLE = "PROVENANCE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


_SAFE_MESSAGES: dict[AIErrorCategory, str] = {
    AIErrorCategory.GATEWAY_DISABLED: "AI execution is currently disabled.",
    AIErrorCategory.TASK_DISABLED: "This AI task is currently disabled.",
    AIErrorCategory.PROVIDER_DISABLED: "The approved AI provider is currently disabled.",
    AIErrorCategory.CIRCUIT_OPEN: "AI execution is temporarily unavailable.",
    AIErrorCategory.RESULT_AUTHORITY_REVOKED: (
        "AI execution authority changed before the result could be accepted."
    ),
    AIErrorCategory.POLICY_DENIED: "This AI task is not permitted for the current context.",
    AIErrorCategory.NO_COMPLIANT_ROUTE: "No approved AI execution route is available.",
    AIErrorCategory.UNSUPPORTED_TASK: "The requested AI task is not supported.",
    AIErrorCategory.INVALID_INPUT: "The AI task input is invalid.",
    AIErrorCategory.CONFIGURATION_ERROR: "AI execution is not configured correctly.",
    AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR: "The AI provider is not available.",
    AIErrorCategory.PROVIDER_CREDIT_EXHAUSTED: "AI execution capacity is unavailable.",
    AIErrorCategory.RATE_LIMITED: "AI execution is temporarily rate limited.",
    AIErrorCategory.PROVIDER_UNAVAILABLE: "The AI provider is temporarily unavailable.",
    AIErrorCategory.TIMEOUT: "The AI execution timed out.",
    AIErrorCategory.CONTEXT_LIMIT_EXCEEDED: "The AI task input exceeds the allowed context.",
    AIErrorCategory.COST_LIMIT_EXCEEDED: "The AI execution exceeds the configured cost policy.",
    AIErrorCategory.STRUCTURED_OUTPUT_INVALID: (
        "The AI provider returned invalid structured output."
    ),
    AIErrorCategory.PROVIDER_RESPONSE_INVALID: "The AI provider returned an invalid response.",
    AIErrorCategory.CONTENT_POLICY_DENIED: "The AI provider could not process this content.",
    AIErrorCategory.PII_PROTECTION_FAILED: (
        "Privexa could not apply the PII protection required for this AI task."
    ),
    AIErrorCategory.CLIENT_BOUNDARY_VIOLATION: (
        "One or more AI sources are unavailable in the current client context."
    ),
    AIErrorCategory.PROVENANCE_UNAVAILABLE: (
        "Privexa could not record the AI execution provenance safely."
    ),
    AIErrorCategory.INTERNAL_ERROR: "Privexa could not complete the AI execution safely.",
}


class AIError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    category: AIErrorCategory
    message: str = Field(min_length=1, max_length=255)
    retryable: bool = False
    retry_after_seconds: int | None = Field(default=None, ge=1, le=3600)

    @classmethod
    def safe(
        cls,
        category: AIErrorCategory,
        *,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> AIError:
        return cls(
            category=category,
            message=_SAFE_MESSAGES[category],
            retryable=retryable,
            retry_after_seconds=retry_after_seconds,
        )


class AIPolicyViolation(Exception):
    def __init__(self, category: AIErrorCategory) -> None:
        super().__init__(category.value)
        self.category = category


class AIAvailabilityFailure(Exception):
    """Private availability decision normalized at the Gateway boundary."""

    def __init__(
        self,
        *,
        category: AIErrorCategory,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(category.value)
        self.category = category
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class ProviderFailure(Exception):
    """Private provider diagnostic that is normalized before reaching callers."""

    def __init__(
        self,
        *,
        category: AIErrorCategory,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
        provider_http_status: int | None = None,
        provider_error_category: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(category.value)
        self.category = category
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.provider_http_status = provider_http_status
        self.provider_error_category = provider_error_category
        self.provider_request_id = provider_request_id
