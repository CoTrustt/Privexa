from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fixtures.ai_gateway import build_test_model_route, trusted_ai_context
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from privexa_api.ai_gateway.contracts import AIFinishReason, AIUsage
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.providers.base import AIProviderMetadata, AIProviderResult
from privexa_api.ai_gateway.tasks import SYNTHETIC_TEXT_SUMMARY_TASK
from privexa_api.ai_provenance.enums import (
    AIExecutionEventType,
    AIProvenanceStatus,
    AIProviderAttemptKind,
)
from privexa_api.ai_provenance.errors import AIProvenanceConflict
from privexa_api.ai_provenance.models import AIExecution, AIExecutionEvent
from privexa_api.ai_provenance.repository import AIProvenanceRepository
from privexa_api.ai_provenance.service import DatabaseAIProvenanceRecorder
from privexa_api.db.session import build_session_factory
from privexa_api.db.tenant_scope import apply_client_scope


def _context(tenant_data, *, firm=None, client=None, user=None, membership=None):  # type: ignore[no-untyped-def]
    return trusted_ai_context(
        firm_id=(firm or tenant_data.firm_a).id,
        client_id=(client or tenant_data.apollo_finance).id,
        user_id=(user or tenant_data.alice).id,
        membership_id=(membership or tenant_data.alice_membership).id,
    )


def _start(recorder, context, execution_id, *, started_at=None):  # type: ignore[no-untyped-def]
    recorder.start_execution(
        context=context,
        execution_id=execution_id,
        task=SYNTHETIC_TEXT_SUMMARY_TASK,
        source_references=(),
        workflow_id=None,
        parent_execution_id=None,
        started_at=started_at or datetime.now(UTC),
        trace_id="a" * 32,
        span_id="b" * 16,
        trace_sampled=True,
    )


def _success_result(cost: Decimal | None = Decimal("0.0000001001")) -> AIProviderResult:
    usage = AIUsage(
        prompt_tokens=3,
        completion_tokens=2,
        total_tokens=5,
        reported_cost=cost,
        cost_currency="USD" if cost is not None else None,
    )
    return AIProviderResult(
        output_text='{"summary":"safe"}',
        finish_reason=AIFinishReason.COMPLETED,
        usage=usage,
        metadata=AIProviderMetadata(
            provider="FALLBACK_PROVIDER",
            adapter="test-adapter",
            model="fallback/model",
            request_id="safe-request-id",
        ),
    )


@pytest.mark.parametrize(
    "invalid_assignment",
    ["client_id = NULL", "authorization_scope = 'FIRM'"],
    ids=["client-scope-with-null-client", "firm-scope-with-client"],
)
def test_database_rejects_ai_execution_scope_ownership_contradictions(
    app_engine,
    owner_engine,
    tenant_data,
    invalid_assignment: str,
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    execution_id = uuid4()
    _start(recorder, _context(tenant_data), execution_id)

    with pytest.raises(IntegrityError), Session(owner_engine) as session, session.begin():
        session.execute(
            text(f"UPDATE ai_executions SET {invalid_assignment} WHERE id = :execution_id"),
            {"execution_id": execution_id},
        )

    with Session(owner_engine) as session:
        execution = session.get(AIExecution, execution_id)
    assert execution is not None
    assert execution.client_id == tenant_data.apollo_finance.id
    assert execution.authorization_scope.value == "CLIENT"


def test_incomplete_execution_is_explicitly_non_terminal(
    app_engine, owner_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    execution_id = uuid4()
    _start(recorder, _context(tenant_data), execution_id)

    with Session(owner_engine) as session:
        execution = session.get(AIExecution, execution_id)
        assert execution is not None
        assert execution.status is AIProvenanceStatus.CREATED
        assert execution.completed_at is None
        assert execution.output_hash is None


def test_retry_and_fallback_events_preserve_order_and_summary_counts(
    app_engine, owner_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context = _context(tenant_data)
    execution_id = uuid4()
    route = build_test_model_route()
    _start(recorder, context, execution_id)
    attempt_ids = [uuid4(), uuid4(), uuid4()]
    kinds = [
        AIProviderAttemptKind.PRIMARY,
        AIProviderAttemptKind.RETRY,
        AIProviderAttemptKind.FALLBACK,
    ]
    failure = ProviderFailure(category=AIErrorCategory.PROVIDER_UNAVAILABLE, retryable=True)

    for number, (attempt_id, kind) in enumerate(
        zip(attempt_ids[:2], kinds[:2], strict=True), start=1
    ):
        recorder.start_attempt(
            context=context,
            execution_id=execution_id,
            attempt_id=attempt_id,
            attempt_number=number,
            attempt_kind=kind,
            route=route,
            started_at=datetime.now(UTC),
            span_id=None,
        )
        recorder.finish_attempt_failure(
            context=context,
            execution_id=execution_id,
            attempt_id=attempt_id,
            attempt_number=number,
            attempt_kind=kind,
            error=failure,
            provider=route.provider.value,
            provider_model=route.provider_model,
            duration_ms=5,
            span_id=None,
        )

    recorder.start_attempt(
        context=context,
        execution_id=execution_id,
        attempt_id=attempt_ids[2],
        attempt_number=3,
        attempt_kind=kinds[2],
        route=route,
        started_at=datetime.now(UTC),
        span_id=None,
    )
    recorder.finish_attempt_success(
        context=context,
        execution_id=execution_id,
        attempt_id=attempt_ids[2],
        attempt_number=3,
        attempt_kind=kinds[2],
        result=_success_result(),
        duration_ms=7,
        span_id=None,
    )
    completed_at = datetime.now(UTC)
    recorder.finalize_execution(
        context=context,
        execution_id=execution_id,
        status=AIProvenanceStatus.SUCCEEDED,
        completed_at=completed_at,
        latency_ms=25,
        output_hash="c" * 64,
    )

    with Session(owner_engine) as session:
        execution = session.get(AIExecution, execution_id)
        assert execution is not None
        events = session.scalars(
            select(AIExecutionEvent)
            .where(AIExecutionEvent.execution_id == execution_id)
            .order_by(AIExecutionEvent.sequence_number)
        ).all()
    assert execution.provider_attempt_count == 3
    assert execution.retry_count == 1
    assert execution.fallback_count == 1
    assert execution.status is AIProvenanceStatus.SUCCEEDED
    assert execution.total_tokens == 5
    assert execution.cost_amount == Decimal("0.0000001001")
    assert execution.cost_complete is False
    assert [event.attempt_kind for event in events if event.attempt_kind] == [
        AIProviderAttemptKind.PRIMARY,
        AIProviderAttemptKind.PRIMARY,
        AIProviderAttemptKind.RETRY,
        AIProviderAttemptKind.RETRY,
        AIProviderAttemptKind.FALLBACK,
        AIProviderAttemptKind.FALLBACK,
    ]
    assert [event.event_type for event in events[-2:]] == [
        AIExecutionEventType.PROVIDER_ATTEMPT_SUCCEEDED,
        AIExecutionEventType.EXECUTION_SUCCEEDED,
    ]


def test_zero_cost_and_unknown_cost_remain_distinct(app_engine, owner_engine, tenant_data) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context = _context(tenant_data)
    route = build_test_model_route()
    ids = [uuid4(), uuid4()]
    for execution_id, cost in zip(ids, (Decimal("0"), None), strict=True):
        _start(recorder, context, execution_id)
        attempt_id = uuid4()
        recorder.start_attempt(
            context=context,
            execution_id=execution_id,
            attempt_id=attempt_id,
            attempt_number=1,
            attempt_kind=AIProviderAttemptKind.PRIMARY,
            route=route,
            started_at=datetime.now(UTC),
            span_id=None,
        )
        recorder.finish_attempt_success(
            context=context,
            execution_id=execution_id,
            attempt_id=attempt_id,
            attempt_number=1,
            attempt_kind=AIProviderAttemptKind.PRIMARY,
            result=_success_result(cost),
            duration_ms=1,
            span_id=None,
        )

    with Session(owner_engine) as session:
        zero = session.get(AIExecution, ids[0])
        unknown = session.get(AIExecution, ids[1])
        assert zero is not None and unknown is not None
        assert zero.cost_amount == Decimal("0") and zero.cost_complete is True
        assert unknown.cost_amount is None and unknown.cost_complete is False


def test_identical_finalization_is_idempotent_but_conflict_cannot_rewrite_history(
    app_engine, owner_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context = _context(tenant_data)
    execution_id = uuid4()
    started = datetime.now(UTC)
    completed = started + timedelta(milliseconds=10)
    _start(recorder, context, execution_id, started_at=started)
    kwargs = dict(
        context=context,
        execution_id=execution_id,
        status=AIProvenanceStatus.SUCCEEDED,
        completed_at=completed,
        latency_ms=10,
        output_hash="d" * 64,
    )

    recorder.finalize_execution(**kwargs)
    recorder.finalize_execution(**kwargs)
    with pytest.raises(AIProvenanceConflict):
        recorder.finalize_execution(
            context=context,
            execution_id=execution_id,
            status=AIProvenanceStatus.FAILED,
            completed_at=completed,
            latency_ms=10,
            error_category=AIErrorCategory.INTERNAL_ERROR,
        )

    with Session(owner_engine) as session:
        events = session.scalars(
            select(AIExecutionEvent).where(AIExecutionEvent.execution_id == execution_id)
        ).all()
        execution = session.get(AIExecution, execution_id)
        assert execution is not None
    assert execution.status is AIProvenanceStatus.SUCCEEDED
    success_count = sum(
        event.event_type is AIExecutionEventType.EXECUTION_SUCCEEDED for event in events
    )
    assert success_count == 1


def test_duplicate_attempt_start_is_idempotent_and_sequence_conflict_is_rejected(
    app_engine, owner_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context = _context(tenant_data)
    execution_id = uuid4()
    attempt_id = uuid4()
    route = build_test_model_route()
    started = datetime.now(UTC)
    _start(recorder, context, execution_id)
    kwargs = dict(
        context=context,
        execution_id=execution_id,
        attempt_id=attempt_id,
        attempt_number=1,
        attempt_kind=AIProviderAttemptKind.PRIMARY,
        route=route,
        started_at=started,
        span_id=None,
    )

    recorder.start_attempt(**kwargs)
    recorder.start_attempt(**kwargs)
    with pytest.raises(AIProvenanceConflict):
        recorder.start_attempt(**{**kwargs, "attempt_id": uuid4()})

    with Session(owner_engine) as session:
        execution = session.get(AIExecution, execution_id)
        assert execution is not None
        starts = session.scalars(
            select(AIExecutionEvent).where(
                AIExecutionEvent.execution_id == execution_id,
                AIExecutionEvent.event_type == AIExecutionEventType.PROVIDER_ATTEMPT_STARTED,
            )
        ).all()
    assert execution.provider_attempt_count == 1
    assert len(starts) == 1


def test_parent_execution_must_share_exact_tenant_and_client_scope(
    app_engine, owner_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context = _context(tenant_data)
    parent_id = uuid4()
    child_id = uuid4()
    _start(recorder, context, parent_id)
    now = datetime.now(UTC)
    recorder.start_execution(
        context=context,
        execution_id=child_id,
        task=SYNTHETIC_TEXT_SUMMARY_TASK,
        source_references=(),
        workflow_id=uuid4(),
        parent_execution_id=parent_id,
        started_at=now,
        trace_id=None,
        span_id=None,
        trace_sampled=None,
    )
    with Session(owner_engine) as session:
        child = session.get(AIExecution, child_id)
        assert child is not None and child.parent_execution_id == parent_id

    with pytest.raises(AIProvenanceConflict):
        recorder.start_execution(
            context=_context(tenant_data, client=tenant_data.acme_healthcare),
            execution_id=uuid4(),
            task=SYNTHETIC_TEXT_SUMMARY_TASK,
            source_references=(),
            workflow_id=None,
            parent_execution_id=parent_id,
            started_at=now,
            trace_id=None,
            span_id=None,
            trace_sampled=None,
        )


def test_repository_lookup_cannot_cross_tenant_or_client_scope(app_engine, tenant_data) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context_a = _context(tenant_data)
    context_b = _context(
        tenant_data,
        firm=tenant_data.firm_b,
        client=tenant_data.northstar_retail,
        user=tenant_data.bob,
        membership=tenant_data.bob_membership,
    )
    context_other_client = _context(tenant_data, client=tenant_data.acme_healthcare)
    execution_id = uuid4()
    _start(recorder, context_a, execution_id)

    factory = build_session_factory(app_engine)
    for context in (context_b, context_other_client):
        with factory() as session, session.begin():
            apply_client_scope(session, context.to_client_context())
            assert (
                AIProvenanceRepository.get(session, context=context, execution_id=execution_id)
                is None
            )


def test_child_insert_policy_rejects_same_firm_cross_client_parent_link(
    app_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context_a = _context(tenant_data)
    context_b = _context(tenant_data, client=tenant_data.acme_healthcare)
    execution_id = uuid4()
    _start(recorder, context_a, execution_id)

    factory = build_session_factory(app_engine)
    with pytest.raises(SQLAlchemyError), factory() as session, session.begin():
        apply_client_scope(session, context_b.to_client_context())
        session.execute(
            text(
                "INSERT INTO ai_execution_events "
                "(id, execution_id, firm_id, client_id, sequence_number, "
                "deduplication_key, event_type, event_data) "
                "VALUES (:id, :execution_id, :firm_id, :client_id, 2, "
                "'spoofed.event', 'EXECUTION_FAILED', '{}'::jsonb)"
            ),
            {
                "id": uuid4(),
                "execution_id": execution_id,
                "firm_id": tenant_data.firm_a.id,
                "client_id": tenant_data.acme_healthcare.id,
            },
        )


def test_runtime_role_cannot_mutate_or_delete_historical_events(
    app_engine, owner_engine, tenant_data
) -> None:
    recorder = DatabaseAIProvenanceRecorder(build_session_factory(app_engine))
    context = _context(tenant_data)
    execution_id = uuid4()
    _start(recorder, context, execution_id)
    with Session(owner_engine) as session:
        event_id = session.scalar(
            select(AIExecutionEvent.id).where(AIExecutionEvent.execution_id == execution_id)
        )
        assert event_id is not None

    factory = build_session_factory(app_engine)
    for statement in (
        "UPDATE ai_execution_events SET event_data = '{\"tampered\":true}'::jsonb WHERE id = :id",
        "DELETE FROM ai_execution_events WHERE id = :id",
    ):
        with pytest.raises(SQLAlchemyError), factory() as session, session.begin():
            apply_client_scope(session, context.to_client_context())
            session.execute(text(statement), {"id": event_id})
