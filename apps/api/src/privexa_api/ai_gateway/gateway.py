from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from privexa_api.access_control.errors import AuthorizationProblem
from privexa_api.ai_gateway.availability import (
    AIAvailabilityService,
    AICapability,
    provider_failure_category,
    public_capability,
)
from privexa_api.ai_gateway.contracts import (
    AIExecutionRequest,
    AIExecutionResult,
    AIExecutionStatus,
    AIFinishReason,
    AIInvocationMetadata,
    AIModelAlias,
    AIModelExecutionMetadata,
    AITaskType,
)
from privexa_api.ai_gateway.errors import (
    AIAvailabilityFailure,
    AIError,
    AIErrorCategory,
    AIPolicyViolation,
    ProviderFailure,
)
from privexa_api.ai_gateway.providers.base import (
    AIMessageRole,
    AIProvider,
    AIProviderExecutionControls,
    AIProviderMessage,
    AIProviderRequest,
)
from privexa_api.ai_gateway.routing import AIModelRoute, AIModelRouter, AIProviderName
from privexa_api.ai_gateway.source_authorization import (
    AISourceAuthorizationError,
    AISourceAuthorizer,
)
from privexa_api.ai_gateway.tasks import AITaskDefinition, AITaskRegistry
from privexa_api.ai_gateway.telemetry import (
    AIExecutionTelemetry,
    error_logging_fields,
    provider_failure_logging_fields,
    usage_logging_fields,
)
from privexa_api.ai_policy.contracts import (
    AIPolicyDecision,
    AIPolicyEvaluationRequest,
    AIPolicyReasonCode,
    AIProtectionProfileId,
    EffectiveAIPolicy,
)
from privexa_api.ai_policy.errors import AIBudgetExceeded, AIPolicyDenied, NoCompliantAIRoute
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_protection.contracts import ProtectionResult
from privexa_api.ai_protection.errors import AIProtectionError, PIIDetectionError
from privexa_api.ai_protection.service import AIProtection
from privexa_api.ai_provenance.enums import (
    AIExecutionStage,
    AIProvenanceStatus,
    AIProviderAttemptKind,
)
from privexa_api.ai_provenance.errors import AIProvenanceError
from privexa_api.ai_provenance.hashing import hash_output
from privexa_api.ai_provenance.service import AIProvenanceRecorder
from privexa_api.observability.tracing import ai_span, current_trace_correlation
from privexa_api.security.execution_context import (
    ExecutionContext,
    require_trusted_execution_context,
)
from privexa_api.security.sensitivity import SensitivityPolicy


class AIGateway:
    def __init__(
        self,
        *,
        registry: AITaskRegistry,
        policy: AIPolicyEngine,
        router: AIModelRouter,
        providers: Mapping[AIProviderName, AIProvider],
        telemetry: AIExecutionTelemetry,
        provenance: AIProvenanceRecorder,
        protection: AIProtection | None = None,
        source_authorizer: AISourceAuthorizer | None = None,
        availability: AIAvailabilityService | None = None,
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._router = router
        self._providers = dict(providers)
        self._telemetry = telemetry
        self._provenance = provenance
        self._protection = protection
        self._source_authorizer = source_authorizer or AISourceAuthorizer()
        self._availability = availability or AIAvailabilityService()

    async def execute(
        self,
        *,
        context: ExecutionContext,
        request: AIExecutionRequest,
        session: Session | None = None,
    ) -> AIExecutionResult[BaseModel]:
        execution_id = uuid4()
        started_at = datetime.now(UTC)
        started_clock = monotonic()
        with ai_span(
            "ai.execution",
            attributes={
                "ai.execution.id": str(execution_id),
                "ai.task.id": _task_logging_value(request.task),
            },
        ) as execution_span:
            correlation = current_trace_correlation()
            result = await self._execute(
                context=context,
                request=request,
                session=session,
                execution_id=execution_id,
                started_at=started_at,
                started_clock=started_clock,
                trace_id=correlation.trace_id,
                span_id=correlation.span_id,
                trace_sampled=correlation.sampled,
            )
            execution_span.set_attribute("ai.execution.status", result.status.value)
            execution_span.set_attribute(
                "ai.availability.decision",
                "ALLOW" if result.status is AIExecutionStatus.SUCCEEDED else "DENY",
            )
            if result.error is not None:
                execution_span.set_attribute("ai.failure.category", result.error.category.value)
            return result

    def capability(
        self,
        *,
        context: ExecutionContext,
        task_type: AITaskType,
        session: Session | None = None,
    ) -> AICapability:
        """Return product-safe capability state; this never grants execution authority."""

        try:
            trusted_context = require_trusted_execution_context(context)
            task = self._registry.resolve(task_type)
            decision = self._policy.evaluate(
                session=session,
                request=AIPolicyEvaluationRequest(
                    context=trusted_context,
                    task=task.task,
                    task_version=task.version,
                    required_scope=task.required_scope,
                    required_permission=task.required_permission,
                    requested_agent_authorities=task.requested_agent_authorities,
                ),
            )
            if not decision.is_allowed or decision.effective_policy is None:
                return public_capability(_policy_error_category(decision.reason_code))
            route = self._router.resolve(
                task.model_alias,
                policy=decision.effective_policy,
                sensitivity=trusted_context.effective_sensitivity,
            )
            availability = self._availability.evaluate_provider(
                route,
                acquire_probe=False,
            )
            if availability.allowed:
                return public_capability(None)
            capability = public_capability(provider_failure_category(availability))
            return capability.model_copy(
                update={
                    "retryable": availability.retryable,
                    "retry_after_seconds": availability.retry_after_seconds,
                }
            )
        except AuthorizationProblem:
            return public_capability(AIErrorCategory.POLICY_DENIED)
        except AIPolicyViolation as error:
            return public_capability(error.category)
        except NoCompliantAIRoute:
            return public_capability(AIErrorCategory.CONFIGURATION_ERROR)
        except Exception:
            return public_capability(AIErrorCategory.INTERNAL_ERROR)

    async def _execute(
        self,
        *,
        context: ExecutionContext,
        request: AIExecutionRequest,
        session: Session | None,
        execution_id: UUID,
        started_at: datetime,
        started_clock: float,
        trace_id: str | None,
        span_id: str | None,
        trace_sampled: bool | None,
    ) -> AIExecutionResult[BaseModel]:
        trusted_context: ExecutionContext | None = None
        task: AITaskDefinition | None = None
        decision: AIPolicyDecision | None = None
        model_alias: AIModelAlias | None = None
        provider_name: str | None = None
        provider_model: str | None = None
        provider_request_id: str | None = None
        route: AIModelRoute | None = None
        provenance_started = False
        attempt_id: UUID | None = None
        attempt_started_clock: float | None = None
        attempt_finished = False
        attempt_span_id: str | None = None

        try:
            trusted_context = require_trusted_execution_context(context)
            task = self._registry.find(request.task)
            invocation_metadata = (
                request.metadata
                if isinstance(request.metadata, AIInvocationMetadata)
                else AIInvocationMetadata()
            )
            source_references = ()
            source_authorization_error: AISourceAuthorizationError | None = None
            if task is not None and request.source_references and task.allowed_source_types:
                try:
                    source_references = self._source_authorizer.authorize(
                        session=session,
                        context=trusted_context,
                        allowed_source_types=task.allowed_source_types,
                        source_references=request.source_references,
                    )
                except AISourceAuthorizationError as error:
                    source_authorization_error = error
            self._provenance.start_execution(
                context=trusted_context,
                execution_id=execution_id,
                task=task,
                source_references=source_references,
                workflow_id=invocation_metadata.workflow_id,
                parent_execution_id=invocation_metadata.parent_execution_id,
                started_at=started_at,
                trace_id=trace_id or trusted_context.trace_id,
                span_id=span_id,
                trace_sampled=trace_sampled,
            )
            provenance_started = True
            if source_authorization_error is not None:
                raise source_authorization_error
            validated_input: BaseModel | None = None
            if task is not None:
                validated_input = self._validate_input(task, request.input_data)
                if request.source_references and not task.allowed_source_types:
                    raise AIPolicyViolation(AIErrorCategory.INVALID_INPUT)

            policy_request = _policy_request(
                context=trusted_context,
                request=request,
                task=task,
            )
            policy_clock = monotonic()
            with ai_span(
                "ai.policy.evaluate",
                attributes={"ai.execution.id": str(execution_id)},
            ):
                decision = self._policy.evaluate(session=session, request=policy_request)
                policy_span = current_trace_correlation()
            self._provenance.record_policy(
                context=trusted_context,
                execution_id=execution_id,
                decision=decision,
                duration_ms=_duration_ms(policy_clock),
                span_id=policy_span.span_id,
            )
            if not decision.is_allowed:
                raise AIPolicyDenied(decision)
            if task is None or validated_input is None or decision.effective_policy is None:
                raise AIPolicyViolation(AIErrorCategory.CONFIGURATION_ERROR)

            effective = decision.effective_policy
            content = task.user_content(validated_input)
            if len(content) > task.constraints.max_input_characters:
                raise AIPolicyViolation(AIErrorCategory.INVALID_INPUT)

            # This is the last point at which provider-visible user content may be raw.
            with ai_span(
                "ai.protection.apply",
                attributes={"ai.execution.id": str(execution_id)},
            ):
                protection_result = self._protect_content(
                    content=content,
                    policy=effective,
                    context=trusted_context,
                    task=task,
                )
                protection_span = current_trace_correlation()
            self._provenance.record_protection(
                context=trusted_context,
                execution_id=execution_id,
                result=protection_result,
                span_id=protection_span.span_id,
            )
            if protection_result.profile_id is not AIProtectionProfileId.NONE:
                self._emit_protection_telemetry(
                    execution_id=execution_id,
                    context=trusted_context,
                    task=task,
                    decision=decision,
                    result=protection_result,
                )

            with ai_span(
                "ai.route.select",
                attributes={"ai.execution.id": str(execution_id)},
            ):
                route = self._router.resolve(
                    task.model_alias,
                    policy=effective,
                    sensitivity=trusted_context.effective_sensitivity,
                )
                route_span = current_trace_correlation()
            self._provenance.record_route(
                context=trusted_context,
                execution_id=execution_id,
                route=route,
                span_id=route_span.span_id,
            )
            model_alias = route.alias
            provider_name = route.provider.value
            provider_model = route.provider_model
            provider = self._providers.get(route.provider)
            if provider is None:
                raise NoCompliantAIRoute(AIPolicyReasonCode.NO_COMPLIANT_ROUTE)

            messages = (
                AIProviderMessage(
                    role=AIMessageRole.SYSTEM,
                    content=task.prompt.system_instruction,
                ),
                AIProviderMessage(
                    role=AIMessageRole.USER,
                    content=protection_result.protected_content,
                ),
            )
            output_schema = task.output_model.model_json_schema()
            input_tokens = _conservative_input_token_upper_bound(messages, output_schema)
            if input_tokens > min(effective.max_input_tokens, task.constraints.max_input_tokens):
                raise AIBudgetExceeded
            if (
                _worst_case_cost(
                    route=route,
                    input_tokens=input_tokens,
                    output_tokens=effective.max_output_tokens,
                )
                > effective.max_cost_usd
            ):
                raise AIBudgetExceeded

            self._telemetry.emit(
                "ai.execution.started",
                execution_id=execution_id,
                context=trusted_context,
                fields={
                    "task": task.task.value,
                    "task_version": task.version,
                    "policy_decision_id": decision.decision_id,
                    "policy_version": decision.policy_version,
                    "started_at": started_at,
                    "source_reference_count": len(request.source_references),
                    "workflow_id": invocation_metadata.workflow_id,
                },
            )

            provider_request = AIProviderRequest(
                route=route,
                controls=AIProviderExecutionControls(
                    policy_decision_id=decision.decision_id,
                    policy_version=decision.policy_version,
                    zdr_requirement=effective.zdr_requirement,
                    fallback_policy=effective.fallback_policy,
                    max_cost_usd=effective.max_cost_usd,
                ),
                messages=messages,
                output_schema_name=f"{task.task.value}_v{task.version}",
                output_json_schema=output_schema,
                max_output_tokens=effective.max_output_tokens,
                timeout_seconds=effective.timeout_seconds,
            )
            # Authority is deliberately re-evaluated immediately before model I/O.
            # A stale browser capability response never authorizes this attempt.
            pre_attempt_decision = self._policy.evaluate(
                session=session,
                request=policy_request,
            )
            if not pre_attempt_decision.is_allowed:
                raise AIPolicyDenied(pre_attempt_decision)
            provider_availability = self._availability.evaluate_provider(
                route,
                acquire_probe=True,
            )
            if not provider_availability.allowed:
                raise AIAvailabilityFailure(
                    category=provider_failure_category(provider_availability),
                    retryable=provider_availability.retryable,
                    retry_after_seconds=provider_availability.retry_after_seconds,
                )
            attempt_id = uuid4()
            attempt_started_clock = monotonic()
            with ai_span(
                "ai.provider.attempt",
                attributes={
                    "ai.execution.id": str(execution_id),
                    "ai.attempt.id": str(attempt_id),
                    "gen_ai.system": route.provider.value,
                    "gen_ai.request.model": route.provider_model,
                    "ai.circuit.state": (
                        provider_availability.circuit_state.value
                        if provider_availability.circuit_state is not None
                        else None
                    ),
                },
            ):
                attempt_span_id = current_trace_correlation().span_id
                self._provenance.start_attempt(
                    context=trusted_context,
                    execution_id=execution_id,
                    attempt_id=attempt_id,
                    attempt_number=1,
                    attempt_kind=AIProviderAttemptKind.PRIMARY,
                    route=route,
                    started_at=datetime.now(UTC),
                    span_id=attempt_span_id,
                )
                provider_result = await provider.execute(provider_request)
            provider_name = provider_result.metadata.provider
            provider_model = provider_result.metadata.model
            provider_request_id = provider_result.metadata.request_id
            if provider_result.finish_reason is not AIFinishReason.COMPLETED:
                category = (
                    AIErrorCategory.CONTENT_POLICY_DENIED
                    if provider_result.finish_reason
                    in {AIFinishReason.CONTENT_FILTERED, AIFinishReason.REFUSED}
                    else AIErrorCategory.STRUCTURED_OUTPUT_INVALID
                )
                raise ProviderFailure(category=category, provider_request_id=provider_request_id)
            try:
                output = task.output_model.model_validate_json(provider_result.output_text)
            except ValidationError as error:
                raise ProviderFailure(
                    category=AIErrorCategory.STRUCTURED_OUTPUT_INVALID,
                    provider_request_id=provider_request_id,
                ) from error

            if not self._availability.record_success(route):
                raise AIAvailabilityFailure(
                    category=AIErrorCategory.CONFIGURATION_ERROR,
                )

            self._provenance.finish_attempt_success(
                context=trusted_context,
                execution_id=execution_id,
                attempt_id=attempt_id,
                attempt_number=1,
                attempt_kind=AIProviderAttemptKind.PRIMARY,
                result=provider_result,
                duration_ms=_duration_ms(attempt_started_clock),
                span_id=attempt_span_id,
            )
            attempt_finished = True

            # In-flight HTTP cancellation is not guaranteed. Recheck all material
            # authority before accepting output into deterministic application state.
            acceptance_decision = self._policy.evaluate(
                session=session,
                request=policy_request,
            )
            if not acceptance_decision.is_allowed:
                decision = acceptance_decision
                raise AIAvailabilityFailure(
                    category=AIErrorCategory.RESULT_AUTHORITY_REVOKED,
                )
            acceptance_availability = self._availability.evaluate_provider(
                route,
                acquire_probe=False,
            )
            if not acceptance_availability.allowed:
                raise AIAvailabilityFailure(
                    category=AIErrorCategory.RESULT_AUTHORITY_REVOKED,
                )

            completed_at, latency_ms = _completion_time(started_clock)
            output_sensitivity = SensitivityPolicy.classify_derived(
                sources=[trusted_context.effective_sensitivity]
            )
            output_hash = hash_output(output)
            self._provenance.finalize_execution(
                context=trusted_context,
                execution_id=execution_id,
                status=AIProvenanceStatus.SUCCEEDED,
                completed_at=completed_at,
                latency_ms=latency_ms,
                output_hash=output_hash,
            )
            self._telemetry.emit(
                "ai.execution.completed",
                execution_id=execution_id,
                context=trusted_context,
                fields={
                    "task": task.task.value,
                    "task_version": task.version,
                    "policy_decision_id": decision.decision_id,
                    "policy_version": decision.policy_version,
                    "provider": provider_name,
                    "provider_model": provider_model,
                    "model_alias": model_alias.value,
                    "provider_request_id": provider_request_id,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "latency_ms": latency_ms,
                    "status": AIExecutionStatus.SUCCEEDED.value,
                    "finish_reason": provider_result.finish_reason.value,
                    "output_hash": output_hash,
                    **usage_logging_fields(provider_result.usage),
                },
            )
            return AIExecutionResult[BaseModel](
                execution_id=execution_id,
                task=request.task,
                task_version=task.version,
                status=AIExecutionStatus.SUCCEEDED,
                result=output,
                usage=provider_result.usage,
                execution=_execution_metadata(
                    decision=decision,
                    model_alias=model_alias,
                    provider=provider_name,
                    provider_model=provider_model,
                    provider_request_id=provider_request_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=latency_ms,
                ),
                finish_reason=provider_result.finish_reason,
                output_sensitivity=output_sensitivity,
            )
        except asyncio.CancelledError:
            if provenance_started and trusted_context is not None:
                completed_at, latency_ms = _completion_time(started_clock)
                try:
                    self._provenance.finalize_execution(
                        context=trusted_context,
                        execution_id=execution_id,
                        status=AIProvenanceStatus.CANCELLED,
                        completed_at=completed_at,
                        latency_ms=latency_ms,
                        error_stage=AIExecutionStage.CANCELLATION,
                    )
                except AIProvenanceError:
                    self._telemetry.provenance_failure(
                        execution_id=execution_id,
                        context=trusted_context,
                        stage="CANCELLATION",
                    )
            raise
        except AIProvenanceError:
            return self._provenance_failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                started_at=started_at,
                started_clock=started_clock,
            )
        except AIPolicyDenied as error:
            decision = error.decision
            category = _policy_error_category(decision.reason_code)
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(category),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields={
                    **error_logging_fields(category),
                    "policy_reason_code": decision.reason_code.value,
                },
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.POLICY,
            )
        except AIAvailabilityFailure as error:
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(
                    error.category,
                    retryable=error.retryable,
                    retry_after_seconds=error.retry_after_seconds,
                ),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields={
                    **error_logging_fields(error.category),
                    "retryable": error.retryable,
                    "retry_after_seconds": error.retry_after_seconds,
                },
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.ROUTING,
            )
        except AISourceAuthorizationError as error:
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(error.category),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields={
                    **error_logging_fields(error.category),
                    "source_validation_reason": error.reason.value,
                    "attempted_source_reference_count": error.attempted_count,
                    "authorized_source_reference_count": 0,
                },
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.VALIDATION,
            )
        except NoCompliantAIRoute as error:
            category = (
                AIErrorCategory.COST_LIMIT_EXCEEDED
                if error.reason_code is AIPolicyReasonCode.BUDGET_EXCEEDED
                else AIErrorCategory.NO_COMPLIANT_ROUTE
            )
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(category),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields={
                    **error_logging_fields(category),
                    "policy_reason_code": error.reason_code.value,
                },
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.ROUTING,
            )
        except AIPolicyViolation as error:
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(error.category),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields=error_logging_fields(error.category),
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.VALIDATION,
            )
        except AIProtectionError as error:
            category = AIErrorCategory.PII_PROTECTION_FAILED
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(category),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields={
                    **error_logging_fields(category),
                    "protection_failure_category": type(error).__name__,
                },
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.PROTECTION,
            )
        except AuthorizationProblem:
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.REJECTED,
                error=AIError.safe(AIErrorCategory.POLICY_DENIED),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                logging_fields=error_logging_fields(AIErrorCategory.POLICY_DENIED),
                provenance_started=provenance_started,
                error_stage=AIExecutionStage.POLICY,
            )
        except ProviderFailure as error:
            if route is not None:
                self._availability.record_failure(route, error.category)
            if (
                provenance_started
                and trusted_context is not None
                and attempt_id is not None
                and attempt_started_clock is not None
                and not attempt_finished
            ):
                try:
                    self._provenance.finish_attempt_failure(
                        context=trusted_context,
                        execution_id=execution_id,
                        attempt_id=attempt_id,
                        attempt_number=1,
                        attempt_kind=AIProviderAttemptKind.PRIMARY,
                        error=error,
                        provider=provider_name,
                        provider_model=provider_model,
                        duration_ms=_duration_ms(attempt_started_clock),
                        span_id=attempt_span_id,
                    )
                    attempt_finished = True
                except AIProvenanceError:
                    return self._provenance_failure(
                        execution_id=execution_id,
                        request=request,
                        task=task,
                        context=trusted_context,
                        decision=decision,
                        model_alias=model_alias,
                        provider=provider_name,
                        provider_model=provider_model,
                        provider_request_id=error.provider_request_id,
                        started_at=started_at,
                        started_clock=started_clock,
                    )
            return self._failure(
                execution_id=execution_id,
                request=request,
                task=task,
                context=trusted_context,
                decision=decision,
                started_at=started_at,
                started_clock=started_clock,
                status=AIExecutionStatus.FAILED,
                error=AIError.safe(
                    error.category,
                    retryable=error.retryable,
                    retry_after_seconds=error.retry_after_seconds,
                ),
                model_alias=model_alias,
                provider=provider_name,
                provider_model=provider_model,
                provider_request_id=error.provider_request_id or provider_request_id,
                logging_fields=provider_failure_logging_fields(error),
                provenance_started=provenance_started,
                error_stage=(
                    AIExecutionStage.OUTPUT_VALIDATION
                    if error.category is AIErrorCategory.STRUCTURED_OUTPUT_INVALID
                    else AIExecutionStage.PROVIDER
                ),
            )
        except Exception as error:
            completed_at, latency_ms = _completion_time(started_clock)
            if provenance_started and trusted_context is not None:
                try:
                    if (
                        attempt_id is not None
                        and attempt_started_clock is not None
                        and not attempt_finished
                    ):
                        self._provenance.finish_attempt_failure(
                            context=trusted_context,
                            execution_id=execution_id,
                            attempt_id=attempt_id,
                            attempt_number=1,
                            attempt_kind=AIProviderAttemptKind.PRIMARY,
                            error=ProviderFailure(category=AIErrorCategory.INTERNAL_ERROR),
                            provider=provider_name,
                            provider_model=provider_model,
                            duration_ms=_duration_ms(attempt_started_clock),
                            span_id=attempt_span_id,
                        )
                    self._provenance.finalize_execution(
                        context=trusted_context,
                        execution_id=execution_id,
                        status=AIProvenanceStatus.FAILED,
                        completed_at=completed_at,
                        latency_ms=latency_ms,
                        error_stage=AIExecutionStage.INTERNAL,
                        error_category=AIErrorCategory.INTERNAL_ERROR,
                    )
                except AIProvenanceError:
                    return self._provenance_failure(
                        execution_id=execution_id,
                        request=request,
                        task=task,
                        context=trusted_context,
                        decision=decision,
                        model_alias=model_alias,
                        provider=provider_name,
                        provider_model=provider_model,
                        provider_request_id=provider_request_id,
                        started_at=started_at,
                        started_clock=started_clock,
                    )
            self._telemetry.unexpected_failure(
                execution_id=execution_id,
                context=trusted_context,
                fields={
                    "task": _task_logging_value(request.task),
                    "task_version": task.version if task is not None else None,
                    "policy_decision_id": decision.decision_id if decision else None,
                    "policy_version": decision.policy_version if decision else None,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "latency_ms": latency_ms,
                    "status": AIExecutionStatus.FAILED.value,
                    "error_category": AIErrorCategory.INTERNAL_ERROR.value,
                },
                error=error,
            )
            return AIExecutionResult[BaseModel](
                execution_id=execution_id,
                task=_known_task(request.task),
                task_version=task.version if task is not None else None,
                status=AIExecutionStatus.FAILED,
                error=AIError.safe(AIErrorCategory.INTERNAL_ERROR),
                execution=_execution_metadata(
                    decision=decision,
                    model_alias=model_alias,
                    provider=provider_name,
                    provider_model=provider_model,
                    provider_request_id=provider_request_id,
                    started_at=started_at,
                    completed_at=completed_at,
                    latency_ms=latency_ms,
                ),
            )

    async def aclose(self) -> None:
        seen: set[int] = set()
        for provider in self._providers.values():
            if id(provider) in seen:
                continue
            seen.add(id(provider))
            await provider.aclose()

    def validate_policy_startup(self, session: Session) -> None:
        self._policy.validate_startup(session)

    def _protect_content(
        self,
        *,
        content: str,
        policy: EffectiveAIPolicy,
        context: ExecutionContext,
        task: AITaskDefinition,
    ) -> ProtectionResult:
        if policy.protection_profile is AIProtectionProfileId.NONE:
            return ProtectionResult(
                protected_content=content,
                profile_id=AIProtectionProfileId.NONE,
                protection_applied=False,
                duration_ms=0,
            )
        if self._protection is None:
            raise PIIDetectionError
        return self._protection.protect(
            content=content,
            policy=policy,
            context=context,
            task=task.task,
        )

    def _emit_protection_telemetry(
        self,
        *,
        execution_id: UUID,
        context: ExecutionContext,
        task: AITaskDefinition,
        decision: AIPolicyDecision,
        result: ProtectionResult,
    ) -> None:
        self._telemetry.emit(
            "ai.protection.completed",
            execution_id=execution_id,
            context=context,
            fields={
                "task": task.task.value,
                "task_version": task.version,
                "policy_decision_id": decision.decision_id,
                "policy_version": decision.policy_version,
                "protection_profile": result.profile_id.value,
                "protection_required": True,
                "protection_applied": result.protection_applied,
                "entity_types": [summary.entity_type for summary in result.entity_summaries],
                "entity_counts": {
                    summary.entity_type: summary.count for summary in result.entity_summaries
                },
                "transformation_modes": sorted(
                    {summary.action.value for summary in result.entity_summaries}
                ),
                "pii_entity_count": result.detected_entity_count,
                "protection_duration_ms": result.duration_ms,
            },
        )

    @staticmethod
    def _validate_input(task: AITaskDefinition, input_data: BaseModel) -> BaseModel:
        if not isinstance(input_data, task.input_model):
            raise AIPolicyViolation(AIErrorCategory.INVALID_INPUT)
        try:
            return task.input_model.model_validate(input_data.model_dump())
        except ValidationError as error:
            raise AIPolicyViolation(AIErrorCategory.INVALID_INPUT) from error

    def _failure(
        self,
        *,
        execution_id: UUID,
        request: AIExecutionRequest,
        task: AITaskDefinition | None,
        context: ExecutionContext | None,
        decision: AIPolicyDecision | None,
        started_at: datetime,
        started_clock: float,
        status: AIExecutionStatus,
        error: AIError,
        model_alias: AIModelAlias | None,
        provider: str | None,
        provider_model: str | None,
        provider_request_id: str | None,
        logging_fields: Mapping[str, object | None],
        provenance_started: bool,
        error_stage: AIExecutionStage,
    ) -> AIExecutionResult[BaseModel]:
        completed_at, latency_ms = _completion_time(started_clock)
        if provenance_started and context is not None:
            try:
                self._provenance.finalize_execution(
                    context=context,
                    execution_id=execution_id,
                    status=(
                        AIProvenanceStatus.REJECTED
                        if status is AIExecutionStatus.REJECTED
                        else AIProvenanceStatus.FAILED
                    ),
                    completed_at=completed_at,
                    latency_ms=latency_ms,
                    error_stage=error_stage,
                    error_category=error.category,
                )
            except AIProvenanceError:
                return self._provenance_failure(
                    execution_id=execution_id,
                    request=request,
                    task=task,
                    context=context,
                    decision=decision,
                    model_alias=model_alias,
                    provider=provider,
                    provider_model=provider_model,
                    provider_request_id=provider_request_id,
                    started_at=started_at,
                    started_clock=started_clock,
                )
        event = (
            "ai.execution.denied" if status is AIExecutionStatus.REJECTED else "ai.execution.failed"
        )
        self._telemetry.emit(
            event,
            execution_id=execution_id,
            context=context,
            fields={
                "task": _task_logging_value(request.task),
                "task_version": task.version if task is not None else None,
                "policy_decision_id": decision.decision_id if decision else None,
                "policy_version": decision.policy_version if decision else None,
                "provider": provider,
                "provider_model": provider_model,
                "model_alias": model_alias.value if model_alias is not None else None,
                "provider_request_id": provider_request_id,
                "started_at": started_at,
                "completed_at": completed_at,
                "latency_ms": latency_ms,
                "status": status.value,
                **logging_fields,
            },
        )
        return AIExecutionResult[BaseModel](
            execution_id=execution_id,
            task=_known_task(request.task),
            task_version=task.version if task is not None else None,
            status=status,
            error=error,
            execution=_execution_metadata(
                decision=decision,
                model_alias=model_alias,
                provider=provider,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
            ),
        )

    def _provenance_failure(
        self,
        *,
        execution_id: UUID,
        request: AIExecutionRequest,
        task: AITaskDefinition | None,
        context: ExecutionContext | None,
        decision: AIPolicyDecision | None,
        model_alias: AIModelAlias | None,
        provider: str | None,
        provider_model: str | None,
        provider_request_id: str | None,
        started_at: datetime,
        started_clock: float,
    ) -> AIExecutionResult[BaseModel]:
        """Fail closed: no successful output crosses an incomplete provenance boundary."""

        completed_at, latency_ms = _completion_time(started_clock)
        self._telemetry.provenance_failure(
            execution_id=execution_id,
            context=context,
            stage="PERSISTENCE",
        )
        return AIExecutionResult[BaseModel](
            execution_id=execution_id,
            task=_known_task(request.task),
            task_version=task.version if task is not None else None,
            status=AIExecutionStatus.FAILED,
            error=AIError.safe(AIErrorCategory.PROVENANCE_UNAVAILABLE),
            execution=_execution_metadata(
                decision=decision,
                model_alias=model_alias,
                provider=provider,
                provider_model=provider_model,
                provider_request_id=provider_request_id,
                started_at=started_at,
                completed_at=completed_at,
                latency_ms=latency_ms,
            ),
        )


def _policy_request(
    *,
    context: ExecutionContext,
    request: AIExecutionRequest,
    task: AITaskDefinition | None,
) -> AIPolicyEvaluationRequest:
    values = {
        "context": context,
        "task": request.task,
        "task_version": task.version if task is not None else None,
        "required_scope": task.required_scope if task is not None else None,
        "required_permission": task.required_permission if task is not None else None,
        "requested_agent_authorities": (
            task.requested_agent_authorities if task is not None else frozenset()
        ),
        "requested_max_output_tokens": (
            request.constraint_overrides.max_output_tokens
            if request.constraint_overrides is not None
            else None
        ),
        "requested_timeout_seconds": (
            request.constraint_overrides.timeout_seconds
            if request.constraint_overrides is not None
            else None
        ),
    }
    if isinstance(request.task, AITaskType):
        return AIPolicyEvaluationRequest(**values)
    return AIPolicyEvaluationRequest.model_construct(**values)


def _conservative_input_token_upper_bound(
    messages: tuple[AIProviderMessage, ...],
    output_schema: dict[str, object],
) -> int:
    # UTF-8 bytes are a conservative upper bound for common byte-backed tokenizers.
    message_bytes = sum(len(message.content.encode("utf-8")) for message in messages)
    schema_bytes = len(
        json.dumps(output_schema, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    return message_bytes + schema_bytes + 64


def _worst_case_cost(
    *,
    route: AIModelRoute,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    prompt = Decimal(input_tokens) * route.max_prompt_price_per_million_tokens
    completion = Decimal(output_tokens) * route.max_completion_price_per_million_tokens
    return (prompt + completion) / Decimal(1_000_000)


def _policy_error_category(reason: AIPolicyReasonCode) -> AIErrorCategory:
    if reason in {
        AIPolicyReasonCode.FEATURE_DISABLED,
        AIPolicyReasonCode.GLOBAL_DISABLED,
    }:
        return AIErrorCategory.GATEWAY_DISABLED
    if reason is AIPolicyReasonCode.TASK_DISABLED:
        return AIErrorCategory.TASK_DISABLED
    if reason is AIPolicyReasonCode.UNKNOWN_TASK:
        return AIErrorCategory.UNSUPPORTED_TASK
    if reason is AIPolicyReasonCode.BUDGET_EXCEEDED:
        return AIErrorCategory.COST_LIMIT_EXCEEDED
    return AIErrorCategory.POLICY_DENIED


def _execution_metadata(
    *,
    decision: AIPolicyDecision | None,
    model_alias: AIModelAlias | None,
    provider: str | None,
    provider_model: str | None,
    provider_request_id: str | None,
    started_at: datetime,
    completed_at: datetime,
    latency_ms: int,
) -> AIModelExecutionMetadata:
    return AIModelExecutionMetadata(
        model_alias=model_alias,
        provider=provider,
        provider_model=provider_model,
        provider_request_id=provider_request_id,
        started_at=started_at,
        completed_at=completed_at,
        latency_ms=latency_ms,
        policy_decision_id=decision.decision_id if decision is not None else None,
        policy_version=decision.policy_version if decision is not None else None,
    )


def _completion_time(started_clock: float) -> tuple[datetime, int]:
    completed_at = datetime.now(UTC)
    latency_ms = max(0, round((monotonic() - started_clock) * 1_000))
    return completed_at, latency_ms


def _duration_ms(started_clock: float) -> int:
    return max(0, round((monotonic() - started_clock) * 1_000))


def _known_task(value: object) -> AITaskType | None:
    return value if isinstance(value, AITaskType) else None


def _task_logging_value(value: object) -> str | None:
    known = _known_task(value)
    return known.value if known is not None else None
