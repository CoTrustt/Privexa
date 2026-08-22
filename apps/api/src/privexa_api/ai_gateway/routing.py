from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

from privexa_api.ai_gateway.contracts import AIModelAlias
from privexa_api.ai_gateway.errors import AIErrorCategory, AIPolicyViolation
from privexa_api.ai_policy.contracts import (
    AIFallbackPolicy,
    AIModelClass,
    AIPolicyReasonCode,
    AIProviderClass,
    EffectiveAIPolicy,
    ZDRRequirement,
)
from privexa_api.ai_policy.errors import NoCompliantAIRoute
from privexa_api.security.enums import SensitivityLevel


class AIProviderName(StrEnum):
    OPENROUTER = "OPENROUTER"
    DETERMINISTIC = "DETERMINISTIC"


@dataclass(frozen=True, slots=True)
class AIModelRoute:
    alias: AIModelAlias
    provider: AIProviderName
    provider_model: str
    max_prompt_price_per_million_tokens: Decimal
    max_completion_price_per_million_tokens: Decimal
    provider_classes: frozenset[AIProviderClass]
    model_classes: frozenset[AIModelClass]
    supports_zdr: bool
    approved_sensitivities: frozenset[SensitivityLevel]
    supported_fallback_policies: frozenset[AIFallbackPolicy]

    def __post_init__(self) -> None:
        if (
            not self.provider_classes
            or not self.model_classes
            or not self.approved_sensitivities
            or not self.supported_fallback_policies
            or self.max_prompt_price_per_million_tokens <= 0
            or self.max_completion_price_per_million_tokens <= 0
        ):
            raise ValueError("AI model route capability metadata is incomplete")


class AIModelRouter:
    def __init__(
        self,
        routes: Mapping[AIModelAlias, AIModelRoute],
        *,
        approved_provider_models: frozenset[str],
    ) -> None:
        self._routes = MappingProxyType(dict(routes))
        self._approved_provider_models = approved_provider_models

    def resolve(
        self,
        alias: AIModelAlias,
        *,
        policy: EffectiveAIPolicy,
        sensitivity: SensitivityLevel,
    ) -> AIModelRoute:
        route = self._routes.get(alias)
        if route is None or route.provider_model not in self._approved_provider_models:
            raise AIPolicyViolation(AIErrorCategory.CONFIGURATION_ERROR)
        if not route.provider_classes.intersection(policy.allowed_provider_classes):
            raise NoCompliantAIRoute(AIPolicyReasonCode.PROVIDER_CLASS_UNAVAILABLE)
        if not route.model_classes.intersection(policy.allowed_model_classes):
            raise NoCompliantAIRoute(AIPolicyReasonCode.MODEL_CLASS_UNAVAILABLE)
        if sensitivity not in route.approved_sensitivities:
            raise NoCompliantAIRoute(AIPolicyReasonCode.NO_COMPLIANT_ROUTE)
        if policy.zdr_requirement is ZDRRequirement.REQUIRED and not route.supports_zdr:
            raise NoCompliantAIRoute(AIPolicyReasonCode.NO_COMPLIANT_ROUTE)
        if policy.fallback_policy not in route.supported_fallback_policies:
            raise NoCompliantAIRoute(AIPolicyReasonCode.NO_COMPLIANT_ROUTE)
        return route
