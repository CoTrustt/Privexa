from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from privexa_api.access_control.permissions import AuthorizationScope
from privexa_api.ai_gateway.contracts import (
    AISourceReference,
    AIUsage,
)
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.providers.base import AIProviderResult
from privexa_api.ai_gateway.routing import AIModelRoute
from privexa_api.ai_gateway.tasks import AITaskDefinition
from privexa_api.ai_policy.contracts import AIPolicyDecision
from privexa_api.ai_protection.contracts import ProtectionResult
from privexa_api.ai_provenance.enums import (
    AICostBasis,
    AIExecutionEventType,
    AIExecutionStage,
    AIProvenanceStatus,
    AIProviderAttemptKind,
    AIProviderAttemptStatus,
)
from privexa_api.ai_provenance.errors import AIProvenanceError
from privexa_api.ai_provenance.hashing import (
    OUTPUT_CANONICALIZATION,
    OUTPUT_HASH_ALGORITHM,
)
from privexa_api.ai_provenance.models import AIExecution, AIExecutionEvent, AIExecutionSource
from privexa_api.ai_provenance.repository import AIProvenanceRepository
from privexa_api.db.errors import DatabaseSecurityError
from privexa_api.db.tenant_scope import apply_client_scope, apply_firm_scope
from privexa_api.security.execution_context import ExecutionContext


class AIProvenanceRecorder(Protocol):
    def start_execution(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        task: AITaskDefinition | None,
        source_references: Sequence[AISourceReference],
        workflow_id: UUID | None,
        parent_execution_id: UUID | None,
        started_at: datetime,
        trace_id: str | None,
        span_id: str | None,
        trace_sampled: bool | None,
    ) -> None: ...

    def record_policy(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        decision: AIPolicyDecision,
        duration_ms: int,
        span_id: str | None,
    ) -> None: ...

    def record_protection(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        result: ProtectionResult,
        span_id: str | None,
    ) -> None: ...

    def record_route(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        route: AIModelRoute,
        span_id: str | None,
    ) -> None: ...

    def start_attempt(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        attempt_kind: AIProviderAttemptKind,
        route: AIModelRoute,
        started_at: datetime,
        span_id: str | None,
    ) -> None: ...

    def finish_attempt_success(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        attempt_kind: AIProviderAttemptKind,
        result: AIProviderResult,
        duration_ms: int,
        span_id: str | None,
    ) -> None: ...

    def finish_attempt_failure(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        attempt_kind: AIProviderAttemptKind,
        error: ProviderFailure,
        provider: str | None,
        provider_model: str | None,
        duration_ms: int,
        span_id: str | None,
    ) -> None: ...

    def finalize_execution(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        status: AIProvenanceStatus,
        completed_at: datetime,
        latency_ms: int,
        error_stage: AIExecutionStage | None = None,
        error_category: AIErrorCategory | None = None,
        output_hash: str | None = None,
    ) -> None: ...


class DatabaseAIProvenanceRecorder:
    """Persists short, independently committed lifecycle transactions around model I/O."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def start_execution(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        task: AITaskDefinition | None,
        source_references: Sequence[AISourceReference],
        workflow_id: UUID | None,
        parent_execution_id: UUID | None,
        started_at: datetime,
        trace_id: str | None,
        span_id: str | None,
        trace_sampled: bool | None,
    ) -> None:
        prompt = task.prompt if task is not None else None
        execution = AIExecution(
            id=execution_id,
            parent_execution_id=parent_execution_id,
            workflow_id=workflow_id,
            request_id=context.request_id,
            firm_id=context.firm_id,
            client_id=context.client_id,
            user_id=context.user_id,
            membership_id=context.membership_id,
            originating_channel=context.originating_channel,
            authorization_scope=context.authorization_scope,
            authorizing_permission=(task.required_permission.value if task is not None else None),
            task_id=task.task.value if task is not None else None,
            task_version=task.version if task is not None else None,
            prompt_template_id=prompt.template_id if prompt is not None else None,
            prompt_template_version=prompt.version if prompt is not None else None,
            prompt_template_hash=prompt.content_hash if prompt is not None else None,
            sensitivity=context.effective_sensitivity,
            status=AIProvenanceStatus.CREATED,
            source_reference_count=len(source_references),
            started_at=started_at,
            trace_id=trace_id,
            span_id=span_id,
            trace_sampled=trace_sampled,
            last_event_sequence=1,
        )
        event = _event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.EXECUTION_CREATED,
            deduplication_key="execution.created",
            sequence_number=1,
            span_id=span_id,
            event_data={
                "task_id": task.task.value if task is not None else None,
                "task_version": task.version if task is not None else None,
                "prompt_template_id": prompt.template_id if prompt is not None else None,
                "prompt_template_version": prompt.version if prompt is not None else None,
            },
        )
        sources = [
            AIExecutionSource(
                id=uuid4(),
                execution_id=execution_id,
                firm_id=context.firm_id,
                client_id=context.client_id,
                ordinal=index,
                source_type=reference.source_type,
                source_id=reference.source_id,
            )
            for index, reference in enumerate(source_references, start=1)
        ]
        self._write(
            context,
            lambda session: AIProvenanceRepository.create_execution(
                session,
                context=context,
                execution=execution,
                created_event=event,
                sources=sources,
            ),
        )

    def record_policy(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        decision: AIPolicyDecision,
        duration_ms: int,
        span_id: str | None,
    ) -> None:
        effective = decision.effective_policy
        references = [item.model_dump(mode="json") for item in decision.rule_references]
        updates: dict[str, object | None] = {
            "policy_decision_id": decision.decision_id,
            "policy_allowed": decision.is_allowed,
            "policy_reason_code": decision.reason_code.value,
            "policy_version": decision.policy_version,
            "policy_hash": decision.policy_hash,
            "policy_decision_fingerprint": decision.decision_fingerprint,
            "policy_evaluated_at": decision.evaluated_at,
            "policy_rule_references": references,
            "allowed_provider_classes": _values(
                effective.allowed_provider_classes if effective is not None else ()
            ),
            "allowed_model_classes": _values(
                effective.allowed_model_classes if effective is not None else ()
            ),
            "allowed_agent_authorities": _values(
                effective.allowed_agent_authorities if effective is not None else ()
            ),
            "zdr_requirement": effective.zdr_requirement.value if effective else None,
            "redaction_requirement": (effective.redaction_requirement.value if effective else None),
            "protection_profile": effective.protection_profile.value if effective else None,
            "max_input_tokens": effective.max_input_tokens if effective else None,
            "max_output_tokens": effective.max_output_tokens if effective else None,
            "max_cost_usd": effective.max_cost_usd if effective else None,
            "timeout_ms": round(effective.timeout_seconds * 1_000) if effective else None,
            "fallback_policy": effective.fallback_policy.value if effective else None,
        }
        event = _event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.POLICY_EVALUATED,
            deduplication_key="policy.evaluated",
            stage=AIExecutionStage.POLICY,
            span_id=span_id,
            duration_ms=duration_ms,
            event_data={
                "decision_id": str(decision.decision_id),
                "decision": decision.decision.value,
                "reason_code": decision.reason_code.value,
                "policy_version": decision.policy_version,
                "policy_hash": decision.policy_hash,
                "decision_fingerprint": decision.decision_fingerprint,
                "rule_references": references,
            },
        )
        self._append(context, execution_id, event, updates)

    def record_protection(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        result: ProtectionResult,
        span_id: str | None,
    ) -> None:
        summaries = [item.model_dump(mode="json") for item in result.entity_summaries]
        inspected = result.profile_id.value != "NONE"
        event = _event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.PROTECTION_COMPLETED,
            deduplication_key="protection.completed",
            stage=AIExecutionStage.PROTECTION,
            span_id=span_id,
            duration_ms=result.duration_ms,
            event_data={
                "profile_id": result.profile_id.value,
                "inspection_performed": inspected,
                "protection_applied": result.protection_applied,
                "entity_count": result.detected_entity_count,
                "entity_summaries": summaries,
            },
        )
        self._append(
            context,
            execution_id,
            event,
            {
                "pii_inspection_performed": inspected,
                "pii_protection_applied": result.protection_applied,
                "pii_protection_succeeded": True,
                "pii_entity_count": result.detected_entity_count,
                "pii_entity_summary": summaries,
                "pii_protection_duration_ms": result.duration_ms,
            },
        )

    def record_route(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        route: AIModelRoute,
        span_id: str | None,
    ) -> None:
        event = _event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.ROUTE_SELECTED,
            deduplication_key="route.selected",
            stage=AIExecutionStage.ROUTING,
            span_id=span_id,
            provider=route.provider.value,
            provider_model=route.provider_model,
            event_data={
                "model_alias": route.alias.value,
                "provider_classes": _values(route.provider_classes),
                "model_classes": _values(route.model_classes),
                "supports_zdr": route.supports_zdr,
            },
        )
        self._append(
            context,
            execution_id,
            event,
            {
                "selected_model_alias": route.alias.value,
                "selected_provider": route.provider.value,
                "selected_provider_model": route.provider_model,
            },
        )

    def start_attempt(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        attempt_kind: AIProviderAttemptKind,
        route: AIModelRoute,
        started_at: datetime,
        span_id: str | None,
    ) -> None:
        event = _event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.PROVIDER_ATTEMPT_STARTED,
            deduplication_key=f"attempt.{attempt_id}.started",
            stage=AIExecutionStage.PROVIDER,
            occurred_at=started_at,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            attempt_kind=attempt_kind,
            provider=route.provider.value,
            provider_model=route.provider_model,
            span_id=span_id,
        )
        self._append(
            context,
            execution_id,
            event,
            {
                "status": AIProvenanceStatus.EXECUTING,
            },
        )

    def finish_attempt_success(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        attempt_kind: AIProviderAttemptKind,
        result: AIProviderResult,
        duration_ms: int,
        span_id: str | None,
    ) -> None:
        usage = result.usage
        event = _attempt_event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.PROVIDER_ATTEMPT_SUCCEEDED,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            attempt_kind=attempt_kind,
            status=AIProviderAttemptStatus.SUCCEEDED,
            provider=result.metadata.provider,
            provider_adapter=result.metadata.adapter,
            provider_model=result.metadata.model,
            provider_request_id=result.metadata.request_id,
            finish_reason=result.finish_reason.value,
            usage=usage,
            duration_ms=duration_ms,
            span_id=span_id,
        )
        self._append(
            context,
            execution_id,
            event,
            {
                "actual_provider": result.metadata.provider,
                "actual_provider_adapter": result.metadata.adapter,
                "actual_provider_model": result.metadata.model,
                "finish_reason": result.finish_reason.value,
            },
            accumulate_usage=True,
        )

    def finish_attempt_failure(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        attempt_id: UUID,
        attempt_number: int,
        attempt_kind: AIProviderAttemptKind,
        error: ProviderFailure,
        provider: str | None,
        provider_model: str | None,
        duration_ms: int,
        span_id: str | None,
    ) -> None:
        event = _attempt_event(
            context=context,
            execution_id=execution_id,
            event_type=AIExecutionEventType.PROVIDER_ATTEMPT_FAILED,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            attempt_kind=attempt_kind,
            status=AIProviderAttemptStatus.FAILED,
            provider=provider,
            provider_model=provider_model,
            provider_request_id=error.provider_request_id,
            error_category=error.category,
            duration_ms=duration_ms,
            span_id=span_id,
            usage=None,
        )
        self._append(context, execution_id, event, {"cost_complete": False})

    def finalize_execution(
        self,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        status: AIProvenanceStatus,
        completed_at: datetime,
        latency_ms: int,
        error_stage: AIExecutionStage | None = None,
        error_category: AIErrorCategory | None = None,
        output_hash: str | None = None,
    ) -> None:
        if not status.is_terminal:
            raise ValueError("AI provenance finalization requires a terminal status")
        if status is AIProvenanceStatus.SUCCEEDED and output_hash is None:
            raise ValueError("successful AI provenance requires an output hash")
        event_type = {
            AIProvenanceStatus.SUCCEEDED: AIExecutionEventType.EXECUTION_SUCCEEDED,
            AIProvenanceStatus.REJECTED: AIExecutionEventType.EXECUTION_REJECTED,
            AIProvenanceStatus.FAILED: AIExecutionEventType.EXECUTION_FAILED,
            AIProvenanceStatus.CANCELLED: AIExecutionEventType.EXECUTION_CANCELLED,
        }[status]
        event = _event(
            context=context,
            execution_id=execution_id,
            event_type=event_type,
            deduplication_key="execution.finalized",
            stage=error_stage,
            occurred_at=completed_at,
            error_category=error_category.value if error_category else None,
            duration_ms=latency_ms,
            event_data={"status": status.value},
        )
        updates: dict[str, object | None] = {
            "status": status,
            "completed_at": completed_at,
            "latency_ms": latency_ms,
            "error_stage": error_stage,
            "error_category": error_category.value if error_category else None,
            "output_hash": output_hash,
            "output_hash_algorithm": OUTPUT_HASH_ALGORITHM if output_hash else None,
            "output_canonicalization": OUTPUT_CANONICALIZATION if output_hash else None,
        }
        if error_stage is AIExecutionStage.PROTECTION:
            updates["pii_protection_succeeded"] = False
        self._append(
            context,
            execution_id,
            event,
            updates,
        )

    def _append(
        self,
        context: ExecutionContext,
        execution_id: UUID,
        event: AIExecutionEvent,
        updates: dict[str, object | None],
        *,
        accumulate_usage: bool = False,
    ) -> None:
        self._write(
            context,
            lambda session: AIProvenanceRepository.append_event(
                session,
                context=context,
                execution_id=execution_id,
                event=event,
                summary_updates=updates,
                accumulate_usage=accumulate_usage,
            ),
        )

    def _write(self, context: ExecutionContext, operation: Callable[[Session], object]) -> None:
        for attempt in range(2):
            try:
                with self._session_factory() as session, session.begin():
                    _apply_scope(session, context)
                    operation(session)
                return
            except AIProvenanceError:
                raise
            except (SQLAlchemyError, DatabaseSecurityError):
                if attempt == 1:
                    raise AIProvenanceError from None


def _apply_scope(session: Session, context: ExecutionContext) -> None:
    if context.authorization_scope is AuthorizationScope.CLIENT:
        apply_client_scope(session, context.to_client_context())
    else:
        apply_firm_scope(session, context.to_firm_context())


def _values(items: Iterable[StrEnum]) -> list[str]:
    return sorted(item.value for item in items)


def _event(
    *,
    context: ExecutionContext,
    execution_id: UUID,
    event_type: AIExecutionEventType,
    deduplication_key: str,
    sequence_number: int = 0,
    occurred_at: datetime | None = None,
    stage: AIExecutionStage | None = None,
    attempt_id: UUID | None = None,
    attempt_number: int | None = None,
    attempt_kind: AIProviderAttemptKind | None = None,
    provider: str | None = None,
    provider_adapter: str | None = None,
    provider_model: str | None = None,
    provider_request_id: str | None = None,
    attempt_status: AIProviderAttemptStatus | None = None,
    finish_reason: str | None = None,
    error_category: str | None = None,
    duration_ms: int | None = None,
    span_id: str | None = None,
    event_data: dict[str, object] | None = None,
) -> AIExecutionEvent:
    return AIExecutionEvent(
        id=uuid4(),
        execution_id=execution_id,
        firm_id=context.firm_id,
        client_id=context.client_id,
        sequence_number=sequence_number,
        deduplication_key=deduplication_key,
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        stage=stage,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        attempt_kind=attempt_kind,
        provider=provider,
        provider_adapter=provider_adapter,
        provider_model=provider_model,
        provider_request_id=provider_request_id,
        attempt_status=attempt_status,
        finish_reason=finish_reason,
        error_category=error_category,
        duration_ms=duration_ms,
        span_id=span_id,
        event_data=event_data or {},
    )


def _attempt_event(
    *,
    context: ExecutionContext,
    execution_id: UUID,
    event_type: AIExecutionEventType,
    attempt_id: UUID,
    attempt_number: int,
    attempt_kind: AIProviderAttemptKind,
    status: AIProviderAttemptStatus,
    provider: str | None,
    provider_model: str | None,
    duration_ms: int,
    span_id: str | None,
    usage: AIUsage | None,
    provider_adapter: str | None = None,
    provider_request_id: str | None = None,
    finish_reason: str | None = None,
    error_category: AIErrorCategory | None = None,
) -> AIExecutionEvent:
    cost: Decimal | None = usage.reported_cost if usage is not None else None
    return AIExecutionEvent(
        id=uuid4(),
        execution_id=execution_id,
        firm_id=context.firm_id,
        client_id=context.client_id,
        sequence_number=0,
        deduplication_key=f"attempt.{attempt_id}.finished",
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        stage=AIExecutionStage.PROVIDER,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        attempt_kind=attempt_kind,
        provider=provider,
        provider_adapter=provider_adapter,
        provider_model=provider_model,
        provider_request_id=provider_request_id,
        attempt_status=status,
        finish_reason=finish_reason,
        error_category=error_category.value if error_category else None,
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
        total_tokens=usage.total_tokens if usage else None,
        cached_tokens=usage.cached_tokens if usage else None,
        reasoning_tokens=usage.reasoning_tokens if usage else None,
        cost_amount=cost,
        cost_currency=usage.cost_currency if usage else None,
        cost_basis=AICostBasis.PROVIDER_REPORTED if cost is not None else None,
        duration_ms=duration_ms,
        span_id=span_id,
        event_data={},
    )
