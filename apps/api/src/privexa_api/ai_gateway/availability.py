from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from privexa_api.ai_gateway.circuit_breaker import (
    AICircuitBreaker,
    AICircuitState,
    InMemoryAICircuitBreaker,
)
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.provider_controls import (
    AIProviderControlRepository,
    StaticAIProviderControlRepository,
)
from privexa_api.ai_gateway.routing import AIModelRoute


class AIAvailabilityReason(StrEnum):
    AVAILABLE = "AVAILABLE"
    GLOBAL_DISABLED = "GLOBAL_DISABLED"
    TASK_DISABLED = "TASK_DISABLED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    BUDGET_BLOCKED = "BUDGET_BLOCKED"
    CONFIGURATION_UNAVAILABLE = "CONFIGURATION_UNAVAILABLE"
    RESULT_AUTHORITY_REVOKED = "RESULT_AUTHORITY_REVOKED"
    UNEXPECTED_GATEWAY_FAILURE = "UNEXPECTED_GATEWAY_FAILURE"


class AICapabilityState(StrEnum):
    AVAILABLE = "AVAILABLE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    RESTRICTED = "RESTRICTED"


class AICapability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    state: AICapabilityState
    available: bool
    retryable: bool = False
    retry_after_seconds: int | None = Field(default=None, ge=1, le=3600)


class AIProviderAvailability(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    allowed: bool
    reason: AIAvailabilityReason
    retryable: bool = False
    retry_after_seconds: int | None = Field(default=None, ge=1, le=3600)
    circuit_state: AICircuitState | None = None


class AIAvailabilityService:
    def __init__(
        self,
        *,
        controls: AIProviderControlRepository | None = None,
        circuit: AICircuitBreaker | None = None,
    ) -> None:
        self._controls = controls or StaticAIProviderControlRepository()
        self._circuit = circuit or InMemoryAICircuitBreaker()

    def evaluate_provider(
        self,
        route: AIModelRoute,
        *,
        acquire_probe: bool,
    ) -> AIProviderAvailability:
        try:
            if not self._controls.is_enabled(route.provider):
                return AIProviderAvailability(
                    allowed=False,
                    reason=AIAvailabilityReason.PROVIDER_DISABLED,
                )
            permit = (
                self._circuit.before_call(route) if acquire_probe else self._circuit.peek(route)
            )
        except Exception:
            return AIProviderAvailability(
                allowed=False,
                reason=AIAvailabilityReason.CONFIGURATION_UNAVAILABLE,
            )
        if not permit.allowed:
            return AIProviderAvailability(
                allowed=False,
                reason=AIAvailabilityReason.CIRCUIT_OPEN,
                retryable=True,
                retry_after_seconds=permit.retry_after_seconds,
                circuit_state=permit.state,
            )
        return AIProviderAvailability(
            allowed=True,
            reason=AIAvailabilityReason.AVAILABLE,
            circuit_state=permit.state,
        )

    def record_success(self, route: AIModelRoute) -> bool:
        try:
            self._circuit.record_success(route)
        except Exception:
            return False
        return True

    def record_failure(self, route: AIModelRoute, category: AIErrorCategory) -> bool:
        if category not in _CIRCUIT_FAILURES:
            return True
        try:
            self._circuit.record_failure(route)
        except Exception:
            return False
        return True


_CIRCUIT_FAILURES = frozenset(
    {
        AIErrorCategory.PROVIDER_UNAVAILABLE,
        AIErrorCategory.TIMEOUT,
        AIErrorCategory.RATE_LIMITED,
        AIErrorCategory.PROVIDER_RESPONSE_INVALID,
        AIErrorCategory.STRUCTURED_OUTPUT_INVALID,
    }
)


def public_capability(category: AIErrorCategory | None) -> AICapability:
    if category is None:
        return AICapability(state=AICapabilityState.AVAILABLE, available=True)
    if category in {
        AIErrorCategory.TIMEOUT,
        AIErrorCategory.RATE_LIMITED,
        AIErrorCategory.PROVIDER_UNAVAILABLE,
        AIErrorCategory.CIRCUIT_OPEN,
        AIErrorCategory.INTERNAL_ERROR,
        AIErrorCategory.PROVENANCE_UNAVAILABLE,
    }:
        return AICapability(
            state=AICapabilityState.TEMPORARILY_UNAVAILABLE,
            available=False,
            retryable=True,
        )
    if category in {
        AIErrorCategory.POLICY_DENIED,
        AIErrorCategory.COST_LIMIT_EXCEEDED,
        AIErrorCategory.PII_PROTECTION_FAILED,
    }:
        return AICapability(state=AICapabilityState.RESTRICTED, available=False)
    return AICapability(state=AICapabilityState.UNAVAILABLE, available=False)


def provider_failure_category(availability: AIProviderAvailability) -> AIErrorCategory:
    return {
        AIAvailabilityReason.PROVIDER_DISABLED: AIErrorCategory.PROVIDER_DISABLED,
        AIAvailabilityReason.CIRCUIT_OPEN: AIErrorCategory.CIRCUIT_OPEN,
        AIAvailabilityReason.CONFIGURATION_UNAVAILABLE: AIErrorCategory.CONFIGURATION_ERROR,
    }.get(availability.reason, AIErrorCategory.PROVIDER_UNAVAILABLE)
