from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.ai_provenance.enums import AIExecutionEventType, AIProviderAttemptKind
from privexa_api.ai_provenance.errors import AIProvenanceConflict
from privexa_api.ai_provenance.models import AIExecution, AIExecutionEvent, AIExecutionSource
from privexa_api.db.tenant_scope import require_matching_execution_context_scope
from privexa_api.security.execution_context import ExecutionContext


class AIProvenanceRepository:
    @staticmethod
    def create_execution(
        session: Session,
        *,
        context: ExecutionContext,
        execution: AIExecution,
        created_event: AIExecutionEvent,
        sources: Sequence[AIExecutionSource],
    ) -> None:
        require_matching_execution_context_scope(session, context)
        existing = session.get(AIExecution, execution.id)
        if existing is not None:
            immutable_fields = (
                "parent_execution_id",
                "workflow_id",
                "request_id",
                "firm_id",
                "client_id",
                "user_id",
                "membership_id",
                "originating_channel",
                "authorization_scope",
                "authorizing_permission",
                "task_id",
                "task_version",
                "prompt_template_id",
                "prompt_template_version",
                "prompt_template_hash",
                "sensitivity",
                "source_reference_count",
                "started_at",
                "trace_id",
                "span_id",
                "trace_sampled",
            )
            if any(
                getattr(existing, field) != getattr(execution, field) for field in immutable_fields
            ):
                raise AIProvenanceConflict
            existing_sources = session.scalars(
                select(AIExecutionSource)
                .where(AIExecutionSource.execution_id == execution.id)
                .order_by(AIExecutionSource.ordinal)
            ).all()
            expected_sources = [(item.source_type, item.source_id) for item in sources]
            if [
                (item.source_type, item.source_id) for item in existing_sources
            ] != expected_sources:
                raise AIProvenanceConflict
            return
        if execution.parent_execution_id is not None:
            parent = session.scalar(
                select(AIExecution).where(
                    AIExecution.id == execution.parent_execution_id,
                    AIExecution.firm_id == context.firm_id,
                    AIExecution.client_id == context.client_id,
                )
            )
            if parent is None:
                raise AIProvenanceConflict
        session.add(execution)
        session.flush()
        session.add_all([*sources, created_event])
        session.flush()

    @staticmethod
    def append_event(
        session: Session,
        *,
        context: ExecutionContext,
        execution_id: UUID,
        event: AIExecutionEvent,
        summary_updates: Mapping[str, object | None] | None = None,
        accumulate_usage: bool = False,
    ) -> AIExecution:
        require_matching_execution_context_scope(session, context)
        execution = session.scalar(
            select(AIExecution)
            .where(
                AIExecution.id == execution_id,
                AIExecution.firm_id == context.firm_id,
                AIExecution.client_id == context.client_id,
            )
            .with_for_update()
        )
        if execution is None:
            raise AIProvenanceConflict
        duplicate = session.scalar(
            select(AIExecutionEvent).where(
                AIExecutionEvent.execution_id == execution_id,
                AIExecutionEvent.deduplication_key == event.deduplication_key,
            )
        )
        if duplicate is not None:
            if not _same_event_facts(duplicate, event) or any(
                getattr(execution, field) != value
                for field, value in (summary_updates or {}).items()
            ):
                raise AIProvenanceConflict
            return execution
        if execution.status.is_terminal:
            raise AIProvenanceConflict

        event.sequence_number = execution.last_event_sequence + 1
        execution.last_event_sequence = event.sequence_number
        if event.event_type is AIExecutionEventType.PROVIDER_ATTEMPT_STARTED:
            if event.attempt_number != execution.provider_attempt_count + 1:
                raise AIProvenanceConflict
            execution.provider_attempt_count = event.attempt_number
            if event.attempt_kind is AIProviderAttemptKind.RETRY:
                execution.retry_count += 1
            elif event.attempt_kind is AIProviderAttemptKind.FALLBACK:
                execution.fallback_count += 1
        if accumulate_usage:
            prior_unknown_cost = session.scalar(
                select(AIExecutionEvent.id)
                .where(
                    AIExecutionEvent.execution_id == execution_id,
                    AIExecutionEvent.attempt_status.is_not(None),
                    AIExecutionEvent.cost_amount.is_(None),
                )
                .limit(1)
            )
            _accumulate_usage(execution, event, has_unknown_cost=prior_unknown_cost is not None)
        for field, value in (summary_updates or {}).items():
            if not hasattr(execution, field):
                raise AIProvenanceConflict
            setattr(execution, field, value)
        session.add(event)
        session.flush()
        return execution

    @staticmethod
    def get(
        session: Session,
        *,
        context: ExecutionContext,
        execution_id: UUID,
    ) -> AIExecution | None:
        require_matching_execution_context_scope(session, context)
        return session.scalar(
            select(AIExecution).where(
                AIExecution.id == execution_id,
                AIExecution.firm_id == context.firm_id,
                AIExecution.client_id == context.client_id,
            )
        )


def _add_optional(current: int | None, value: int | None) -> int | None:
    if value is None:
        return current
    return value if current is None else current + value


def _accumulate_usage(
    execution: AIExecution,
    event: AIExecutionEvent,
    *,
    has_unknown_cost: bool,
) -> None:
    execution.prompt_tokens = _add_optional(execution.prompt_tokens, event.prompt_tokens)
    execution.completion_tokens = _add_optional(
        execution.completion_tokens, event.completion_tokens
    )
    execution.total_tokens = _add_optional(execution.total_tokens, event.total_tokens)
    execution.cached_tokens = _add_optional(execution.cached_tokens, event.cached_tokens)
    execution.reasoning_tokens = _add_optional(execution.reasoning_tokens, event.reasoning_tokens)
    if event.cost_amount is None:
        execution.cost_complete = False
        return
    if execution.cost_amount is None:
        execution.cost_amount = event.cost_amount
        execution.cost_currency = event.cost_currency
        execution.cost_basis = event.cost_basis
        execution.cost_complete = not has_unknown_cost
        return
    if execution.cost_currency != event.cost_currency or execution.cost_basis != event.cost_basis:
        execution.cost_amount = None
        execution.cost_currency = None
        execution.cost_basis = None
        execution.cost_complete = False
        return
    execution.cost_amount += event.cost_amount
    execution.cost_complete = execution.cost_complete and not has_unknown_cost


def _same_event_facts(existing: AIExecutionEvent, proposed: AIExecutionEvent) -> bool:
    fields = (
        "event_type",
        "stage",
        "attempt_id",
        "attempt_number",
        "attempt_kind",
        "provider",
        "provider_adapter",
        "provider_model",
        "provider_request_id",
        "attempt_status",
        "finish_reason",
        "error_category",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "cached_tokens",
        "reasoning_tokens",
        "cost_amount",
        "cost_currency",
        "cost_basis",
        "duration_ms",
        "span_id",
        "event_data",
    )
    return all(getattr(existing, field) == getattr(proposed, field) for field in fields)
