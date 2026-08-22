from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from privexa_api.ai_gateway.availability import AIAvailabilityService
from privexa_api.ai_gateway.circuit_breaker import (
    AICircuitSettings,
    DatabaseAICircuitBreaker,
)
from privexa_api.ai_gateway.contracts import AIModelAlias
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.provider_controls import DatabaseAIProviderControlRepository
from privexa_api.ai_gateway.providers.deterministic import DeterministicAIProvider
from privexa_api.ai_gateway.providers.openrouter import OpenRouterProvider
from privexa_api.ai_gateway.routing import (
    AIModelRoute,
    AIModelRouter,
    AIProviderName,
)
from privexa_api.ai_gateway.source_authorization import (
    AISourceAuthorizer,
    StoredFileSourceResolver,
)
from privexa_api.ai_gateway.tasks import build_task_registry
from privexa_api.ai_gateway.telemetry import AIExecutionTelemetry
from privexa_api.ai_policy.contracts import (
    AIFallbackPolicy,
    AIModelClass,
    AIProviderClass,
)
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import (
    AIPolicySnapshotRepository,
    DatabaseAIPolicyRepository,
)
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_protection.presidio_adapter import build_presidio_detector
from privexa_api.ai_protection.service import AIProtectionService
from privexa_api.ai_provenance.service import AIProvenanceRecorder, DatabaseAIProvenanceRecorder
from privexa_api.config import Settings
from privexa_api.security.enums import SensitivityLevel


def build_ai_gateway(
    settings: Settings,
    *,
    session_factory: sessionmaker[Session] | None = None,
    provenance: AIProvenanceRecorder | None = None,
    policy_repository: AIPolicySnapshotRepository | None = None,
) -> AIGateway:
    if provenance is None:
        if session_factory is None:
            raise RuntimeError("AI Gateway provenance persistence is not configured")
        provenance = DatabaseAIProvenanceRecorder(session_factory)
    routes: dict[AIModelAlias, AIModelRoute] = {}
    providers = {}
    protection = None
    approved_models = set(settings.ai_approved_openrouter_models)
    if settings.ai_gateway_enabled and settings.ai_provider_mode != "disabled":
        selected_provider = (
            AIProviderName.DETERMINISTIC
            if settings.ai_provider_mode == "deterministic"
            else AIProviderName.OPENROUTER
        )
        provider_model = (
            "deterministic/local-v1"
            if settings.ai_provider_mode == "deterministic"
            else settings.ai_synthetic_text_summary_model
        )
        work_note_model = (
            "deterministic/local-v1"
            if settings.ai_provider_mode == "deterministic"
            else settings.ai_prepare_work_note_model
        )
        if settings.ai_provider_mode == "deterministic":
            approved_models.add("deterministic/local-v1")
        if provider_model is not None:
            routes[AIModelAlias.FAST_GENERAL_V1] = AIModelRoute(
                alias=AIModelAlias.FAST_GENERAL_V1,
                provider=selected_provider,
                provider_model=provider_model,
                max_prompt_price_per_million_tokens=Decimal(
                    settings.ai_max_prompt_price_usd_per_million_tokens
                ),
                max_completion_price_per_million_tokens=Decimal(
                    settings.ai_max_completion_price_usd_per_million_tokens
                ),
                provider_classes=frozenset(
                    {AIProviderClass.ENTERPRISE_APPROVED, AIProviderClass.ZDR_APPROVED}
                ),
                model_classes=frozenset({AIModelClass.GENERAL_APPROVED}),
                supports_zdr=True,
                approved_sensitivities=frozenset({SensitivityLevel.STANDARD}),
                supported_fallback_policies=frozenset({AIFallbackPolicy.NO_FALLBACK}),
            )
        if work_note_model is not None:
            routes[AIModelAlias.PROTECTED_GENERAL_V1] = AIModelRoute(
                alias=AIModelAlias.PROTECTED_GENERAL_V1,
                provider=selected_provider,
                provider_model=work_note_model,
                max_prompt_price_per_million_tokens=Decimal(
                    settings.ai_max_prompt_price_usd_per_million_tokens
                ),
                max_completion_price_per_million_tokens=Decimal(
                    settings.ai_max_completion_price_usd_per_million_tokens
                ),
                provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
                model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
                supports_zdr=True,
                approved_sensitivities=frozenset({SensitivityLevel.SENSITIVE}),
                supported_fallback_policies=frozenset({AIFallbackPolicy.NO_FALLBACK}),
            )
        if settings.ai_provider_mode == "deterministic":
            providers[AIProviderName.DETERMINISTIC] = DeterministicAIProvider()
        elif settings.openrouter_api_key is not None:
            providers[AIProviderName.OPENROUTER] = OpenRouterProvider(
                api_key=settings.openrouter_api_key
            )
        protection = AIProtectionService(
            detector=build_presidio_detector(model_name="en_core_web_sm")
        )
    policy_registry = build_policy_registry(
        max_cost_usd=settings.ai_max_cost_usd_per_request,
        max_timeout_seconds=settings.ai_request_timeout_seconds,
    )
    task_registry = build_task_registry()
    for task in policy_registry.registered_tasks():
        task_registry.resolve(task)
    availability = None
    if session_factory is not None:
        circuit_settings = AICircuitSettings(
            failure_threshold=settings.ai_circuit_failure_threshold,
            failure_window_seconds=settings.ai_circuit_failure_window_seconds,
            open_seconds=settings.ai_circuit_open_seconds,
            half_open_success_threshold=(settings.ai_circuit_half_open_success_threshold),
            probe_lease_seconds=settings.ai_circuit_probe_lease_seconds,
        )
        availability = AIAvailabilityService(
            controls=DatabaseAIProviderControlRepository(session_factory),
            circuit=DatabaseAICircuitBreaker(session_factory, circuit_settings),
        )
    return AIGateway(
        registry=task_registry,
        policy=AIPolicyEngine(
            evaluator=AIPolicyEvaluator(policy_registry),
            repository=policy_repository or DatabaseAIPolicyRepository(),
            deployment_enabled=settings.ai_gateway_enabled,
        ),
        router=AIModelRouter(
            routes,
            approved_provider_models=frozenset(approved_models),
        ),
        providers=providers,
        telemetry=AIExecutionTelemetry(),
        protection=protection,
        provenance=provenance,
        source_authorizer=AISourceAuthorizer((StoredFileSourceResolver(),)),
        availability=availability,
    )
