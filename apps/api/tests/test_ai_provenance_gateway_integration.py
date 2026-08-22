from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
from dataclasses import replace
from decimal import Decimal
from uuid import uuid4

import pytest
from fixtures.ai_gateway import (
    FakeAIProvider,
    build_test_model_route,
    build_test_policy_engine,
    trusted_ai_context,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from privexa_api.access_control.permissions import Permission
from privexa_api.ai_gateway.availability import AIAvailabilityService
from privexa_api.ai_gateway.circuit_breaker import AICircuitSettings, InMemoryAICircuitBreaker
from privexa_api.ai_gateway.contracts import (
    AIExecutionRequest,
    AIExecutionStatus,
    AIFinishReason,
    AISourceReference,
    AIUsage,
)
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.prompts import AIPromptTemplate
from privexa_api.ai_gateway.provider_controls import StaticAIProviderControlRepository
from privexa_api.ai_gateway.providers.base import AIProviderMetadata, AIProviderResult
from privexa_api.ai_gateway.routing import AIModelRouter, AIProviderName
from privexa_api.ai_gateway.source_authorization import AISourceAuthorizer
from privexa_api.ai_gateway.tasks import (
    SYNTHETIC_TEXT_SUMMARY_TASK,
    AITaskRegistry,
    SyntheticTextSummaryInput,
    build_task_registry,
)
from privexa_api.ai_gateway.telemetry import LOGGER, AIExecutionTelemetry
from privexa_api.ai_policy.contracts import (
    AIPolicyConstraints,
    AIPolicyRule,
    AIPolicyRuntimeSnapshot,
    AIProtectionProfileId,
    RedactionRequirement,
)
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_protection.contracts import DetectedEntity
from privexa_api.ai_protection.service import AIProtectionService
from privexa_api.ai_provenance.enums import AIExecutionEventType, AIProvenanceStatus
from privexa_api.ai_provenance.errors import AIProvenanceError
from privexa_api.ai_provenance.hashing import hash_output
from privexa_api.ai_provenance.models import AIExecution, AIExecutionEvent, AIExecutionSource
from privexa_api.ai_provenance.service import DatabaseAIProvenanceRecorder
from privexa_api.db.session import build_session_factory
from privexa_api.db.tenant_scope import apply_client_scope

PROMPT_CANARY = "SENSITIVE_PROMPT_CANARY_928374"
SYSTEM_CANARY = "SYSTEM_PROMPT_CANARY_102938"
OUTPUT_CANARY = "MODEL_OUTPUT_CANARY_817263"
SOURCE_CONTENT_CANARY = "SOURCE_CONTENT_CANARY_736251"
SECRET_CANARY = "SECRET_API_KEY_CANARY_192837"


def _context(tenant_data, *, client=None, user=None, membership=None):  # type: ignore[no-untyped-def]
    return trusted_ai_context(
        firm_id=tenant_data.firm_a.id,
        client_id=(client or tenant_data.apollo_finance).id,
        user_id=(user or tenant_data.alice).id,
        membership_id=(membership or tenant_data.alice_membership).id,
    )


def _gateway(
    app_engine,
    provider,
    *,
    enabled: bool = True,
    registry: AITaskRegistry | None = None,
    provenance=None,
    policy=None,
    protection=None,
    source_authorizer=None,
    availability=None,
):  # type: ignore[no-untyped-def]
    route = build_test_model_route()
    return AIGateway(
        registry=registry or build_task_registry(),
        policy=policy or build_test_policy_engine(enabled=enabled),
        router=AIModelRouter(
            {route.alias: route}, approved_provider_models=frozenset({route.provider_model})
        ),
        providers={AIProviderName.OPENROUTER: provider},
        telemetry=AIExecutionTelemetry(),
        provenance=provenance or DatabaseAIProvenanceRecorder(build_session_factory(app_engine)),
        protection=protection,
        source_authorizer=source_authorizer,
        availability=availability,
    )


class _EvidenceSourceResolver:
    source_type = "evidence"
    required_permission = Permission.CLIENT_READ

    def resolve_authorized_ids(self, session, *, context, source_ids):  # type: ignore[no-untyped-def]
        del session, context
        return frozenset(source_ids)


def _request(text: str = "Synthetic release notes.", *, sources=()):  # type: ignore[no-untyped-def]
    return AIExecutionRequest(
        task=SYNTHETIC_TEXT_SUMMARY_TASK.task,
        input_data=SyntheticTextSummaryInput(text=text),
        source_references=tuple(sources),
    )


def _database_text(owner_engine, execution_id) -> str:  # type: ignore[no-untyped-def]
    with Session(owner_engine) as session:
        rows = [session.get(AIExecution, execution_id)]
        rows.extend(
            session.scalars(
                select(AIExecutionEvent).where(AIExecutionEvent.execution_id == execution_id)
            )
        )
        rows.extend(
            session.scalars(
                select(AIExecutionSource).where(AIExecutionSource.execution_id == execution_id)
            )
        )
        payloads = []
        for row in rows:
            assert row is not None
            payloads.append(
                {column.key: getattr(row, column.key) for column in row.__table__.columns}
            )
    return json.dumps(payloads, sort_keys=True, default=str)


class _MutablePolicyRepository(StaticAIPolicyRepository):
    def __init__(self) -> None:
        self.enabled = True

    def load(self, session, *, context, task, sensitivity) -> AIPolicyRuntimeSnapshot:
        return AIPolicyRuntimeSnapshot(
            global_enabled=self.enabled,
            task_enabled=True,
        )


class _AuthorityRevokingProvider(FakeAIProvider):
    def __init__(self, repository: _MutablePolicyRepository) -> None:
        super().__init__(output_text=json.dumps({"summary": OUTPUT_CANARY}))
        self.repository = repository

    async def execute(self, request):  # type: ignore[no-untyped-def]
        result = await super().execute(request)
        self.repository.enabled = False
        return result


@pytest.mark.asyncio
async def test_successful_gateway_execution_automatically_records_complete_safe_provenance(
    app_engine, owner_engine, tenant_data
) -> None:
    source_ids = (uuid4(), uuid4())
    sources = tuple(
        AISourceReference(source_type="evidence", source_id=item) for item in source_ids
    )
    instruction = f"Summarize safely. {SYSTEM_CANARY}"
    prompt = AIPromptTemplate(
        template_id="synthetic_text_summary",
        version="privacy-test-v3",
        system_instruction=instruction,
        content_hash=hashlib.sha256(instruction.encode()).hexdigest(),
    )
    task = replace(
        SYNTHETIC_TEXT_SUMMARY_TASK,
        version="privacy-test-v1",
        prompt=prompt,
        allowed_source_types=frozenset({"evidence"}),
    )
    provider = FakeAIProvider(
        output_text=json.dumps({"summary": OUTPUT_CANARY}),
        usage=AIUsage(
            prompt_tokens=11,
            completion_tokens=7,
            total_tokens=18,
            cached_tokens=2,
            reasoning_tokens=3,
            reported_cost=Decimal("0.0000001234"),
            cost_currency="USD",
        ),
    )
    gateway = _gateway(
        app_engine,
        provider,
        registry=AITaskRegistry({task.task: task}),
        source_authorizer=AISourceAuthorizer((_EvidenceSourceResolver(),)),
    )

    context = _context(tenant_data)
    with Session(app_engine) as source_session, source_session.begin():
        apply_client_scope(source_session, context.to_client_context())
        result = await gateway.execute(
            context=context,
            request=_request(f"{PROMPT_CANARY} {SOURCE_CONTENT_CANARY}", sources=sources),
            session=source_session,
        )

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
        events = session.scalars(
            select(AIExecutionEvent)
            .where(AIExecutionEvent.execution_id == result.execution_id)
            .order_by(AIExecutionEvent.sequence_number)
        ).all()
        stored_sources = session.scalars(
            select(AIExecutionSource)
            .where(AIExecutionSource.execution_id == result.execution_id)
            .order_by(AIExecutionSource.ordinal)
        ).all()

    assert execution.user_id == tenant_data.alice.id
    assert execution.firm_id == tenant_data.firm_a.id
    assert execution.client_id == tenant_data.apollo_finance.id
    assert (execution.task_id, execution.task_version) == (task.task.value, task.version)
    assert (execution.prompt_template_id, execution.prompt_template_version) == (
        prompt.template_id,
        prompt.version,
    )
    assert execution.prompt_template_hash == prompt.content_hash
    assert execution.policy_allowed is True
    assert execution.selected_provider == AIProviderName.OPENROUTER.value
    assert execution.actual_provider == "TEST_PROVIDER"
    assert execution.actual_provider_model == "test/provider-model"
    assert execution.provider_attempt_count == 1
    assert execution.retry_count == execution.fallback_count == 0
    assert (execution.prompt_tokens, execution.completion_tokens, execution.total_tokens) == (
        11,
        7,
        18,
    )
    assert execution.cost_amount == Decimal("0.0000001234")
    assert execution.cost_complete is True
    assert execution.status is AIProvenanceStatus.SUCCEEDED
    assert execution.output_hash == hash_output(result.result)
    assert execution.completed_at is not None and execution.completed_at >= execution.started_at
    assert execution.latency_ms is not None
    assert [item.source_id for item in stored_sources] == list(source_ids)
    assert [item.event_type for item in events] == [
        AIExecutionEventType.EXECUTION_CREATED,
        AIExecutionEventType.POLICY_EVALUATED,
        AIExecutionEventType.PROTECTION_COMPLETED,
        AIExecutionEventType.ROUTE_SELECTED,
        AIExecutionEventType.PROVIDER_ATTEMPT_STARTED,
        AIExecutionEventType.PROVIDER_ATTEMPT_SUCCEEDED,
        AIExecutionEventType.EXECUTION_SUCCEEDED,
    ]
    persisted = _database_text(owner_engine, result.execution_id)
    for canary in (PROMPT_CANARY, SYSTEM_CANARY, OUTPUT_CANARY, SOURCE_CONTENT_CANARY):
        assert canary not in persisted


@pytest.mark.asyncio
async def test_policy_denial_creates_provenance_without_provider_invocation_or_usage(
    app_engine, owner_engine, tenant_data
) -> None:
    provider = FakeAIProvider()

    result = await _gateway(app_engine, provider, enabled=False).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert provider.requests == []
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
        events = session.scalars(
            select(AIExecutionEvent).where(AIExecutionEvent.execution_id == result.execution_id)
        ).all()
    assert execution.status is AIProvenanceStatus.REJECTED
    assert execution.policy_allowed is False
    assert execution.provider_attempt_count == 0
    assert execution.total_tokens is None and execution.cost_amount is None
    assert execution.output_hash is None
    assert not any(
        event.event_type is AIExecutionEventType.PROVIDER_ATTEMPT_STARTED for event in events
    )
    assert PROMPT_CANARY not in _database_text(owner_engine, result.execution_id)


@pytest.mark.parametrize(
    ("policy", "expected_category"),
    [
        (build_test_policy_engine(enabled=False), AIErrorCategory.GATEWAY_DISABLED),
        (
            AIPolicyEngine(
                evaluator=AIPolicyEvaluator(build_policy_registry()),
                repository=StaticAIPolicyRepository(task_enabled=False),
                deployment_enabled=True,
            ),
            AIErrorCategory.TASK_DISABLED,
        ),
    ],
)
@pytest.mark.asyncio
async def test_global_and_task_blocks_have_distinct_zero_cost_provenance(
    app_engine,
    owner_engine,
    tenant_data,
    policy,
    expected_category,
) -> None:  # type: ignore[no-untyped-def]
    provider = FakeAIProvider()

    result = await _gateway(app_engine, provider, policy=policy).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.error is not None and result.error.category is expected_category
    assert provider.requests == []
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.error_category == expected_category.value
    assert (
        execution.provider_attempt_count == execution.retry_count == execution.fallback_count == 0
    )
    assert execution.prompt_tokens is None and execution.completion_tokens is None
    assert execution.total_tokens is None and execution.cost_amount is None
    assert execution.actual_provider is None and execution.output_hash is None
    assert (execution.firm_id, execution.client_id) == (
        tenant_data.firm_a.id,
        tenant_data.apollo_finance.id,
    )
    assert PROMPT_CANARY not in _database_text(owner_engine, result.execution_id)


@pytest.mark.parametrize(
    ("availability", "expected_category"),
    [
        (
            AIAvailabilityService(
                controls=StaticAIProviderControlRepository({AIProviderName.OPENROUTER: False})
            ),
            AIErrorCategory.PROVIDER_DISABLED,
        ),
        (
            AIAvailabilityService(
                circuit=InMemoryAICircuitBreaker(AICircuitSettings(failure_threshold=1))
            ),
            AIErrorCategory.CIRCUIT_OPEN,
        ),
    ],
)
@pytest.mark.asyncio
async def test_provider_and_circuit_blocks_record_no_provider_attempt_or_cost(
    app_engine,
    owner_engine,
    tenant_data,
    availability,
    expected_category,
) -> None:  # type: ignore[no-untyped-def]
    provider = FakeAIProvider()
    if expected_category is AIErrorCategory.CIRCUIT_OPEN:
        availability.record_failure(build_test_model_route(), AIErrorCategory.PROVIDER_UNAVAILABLE)

    result = await _gateway(app_engine, provider, availability=availability).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.error is not None and result.error.category is expected_category
    assert provider.requests == []
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.error_category == expected_category.value
    assert (
        execution.provider_attempt_count == execution.retry_count == execution.fallback_count == 0
    )
    assert execution.prompt_tokens is None and execution.completion_tokens is None
    assert execution.total_tokens is None and execution.cost_amount is None
    assert execution.actual_provider is None and execution.output_hash is None
    assert (execution.firm_id, execution.client_id) == (
        tenant_data.firm_a.id,
        tenant_data.apollo_finance.id,
    )
    assert PROMPT_CANARY not in _database_text(owner_engine, result.execution_id)


@pytest.mark.asyncio
async def test_in_flight_authority_revocation_records_attempt_but_discards_output(
    app_engine,
    owner_engine,
    tenant_data,
) -> None:
    repository = _MutablePolicyRepository()
    policy = AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=repository,
        deployment_enabled=True,
    )
    provider = _AuthorityRevokingProvider(repository)

    result = await _gateway(app_engine, provider, policy=policy).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.result is None
    assert result.error is not None
    assert result.error.category is AIErrorCategory.RESULT_AUTHORITY_REVOKED
    assert len(provider.requests) == 1
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
        event_types = session.scalars(
            select(AIExecutionEvent.event_type).where(
                AIExecutionEvent.execution_id == result.execution_id
            )
        ).all()
    assert execution.status is AIProvenanceStatus.REJECTED
    assert execution.error_category == AIErrorCategory.RESULT_AUTHORITY_REVOKED.value
    assert execution.provider_attempt_count == 1
    assert execution.output_hash is None
    assert AIExecutionEventType.PROVIDER_ATTEMPT_SUCCEEDED in event_types
    assert AIExecutionEventType.EXECUTION_REJECTED in event_types
    assert OUTPUT_CANARY not in _database_text(owner_engine, result.execution_id)


class FailingProvider(FakeAIProvider):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def execute(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        raise self.error


class NoOptionalMetadataProvider(FakeAIProvider):
    async def execute(self, request):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return AIProviderResult(
            output_text=self.output_text,
            finish_reason=AIFinishReason.COMPLETED,
            usage=None,
            metadata=AIProviderMetadata(
                provider="MINIMAL_PROVIDER",
                model=request.route.provider_model,
                request_id=None,
            ),
        )


class CanaryDetector:
    values = {
        "EMAIL_ADDRESS": "PII_EMAIL_CANARY@example.test",
        "PHONE_NUMBER": "+91-9000000000",
        "INDIA_PAN": "ABCPA1234D",
        "PERSON": "PersonCanary",
    }

    def detect(self, content: str, **_: object) -> tuple[DetectedEntity, ...]:
        detected = []
        for entity_type, value in self.values.items():
            start = content.index(value)
            detected.append(
                DetectedEntity(
                    entity_type=entity_type,
                    start=start,
                    end=start + len(value),
                    score=1.0,
                )
            )
        return tuple(detected)


class BrokenDetector:
    def detect(self, content: str, **_: object) -> tuple[DetectedEntity, ...]:
        raise RuntimeError(f"detector failed on {content}")


def _required_pii_policy() -> AIPolicyEngine:
    constraints = AIPolicyConstraints(
        redaction_requirement=RedactionRequirement.REQUIRED,
        protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
    )
    canonical = constraints.model_dump(mode="json", exclude_none=True)
    rule = AIPolicyRule(
        rule_id="test.provenance.pii",
        revision=1,
        constraints=constraints,
        content_hash=hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=StaticAIPolicyRepository(override_rules=(rule,)),
        deployment_enabled=True,
    )


@pytest.mark.asyncio
async def test_pii_provenance_retains_only_aggregate_metadata(
    app_engine, owner_engine, tenant_data
) -> None:
    detector = CanaryDetector()
    raw_values = tuple(detector.values.values())
    content = " ".join(raw_values)
    provider = FakeAIProvider()
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    previous_disabled = LOGGER.disabled
    previous_level = LOGGER.level
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)
    try:
        result = await _gateway(
            app_engine,
            provider,
            policy=_required_pii_policy(),
            protection=AIProtectionService(detector=detector),
        ).execute(context=_context(tenant_data), request=_request(content))
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.disabled = previous_disabled
        LOGGER.setLevel(previous_level)

    assert result.status is AIExecutionStatus.SUCCEEDED
    assert len(provider.requests) == 1
    provider_payload = repr(provider.requests[0])
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.pii_inspection_performed is True
    assert execution.pii_protection_applied is True
    assert execution.pii_protection_succeeded is True
    assert execution.pii_entity_count == 4
    assert {item["entity_type"] for item in execution.pii_entity_summary} == set(detector.values)
    combined = _database_text(owner_engine, result.execution_id) + output.getvalue()
    for value in raw_values:
        assert value not in combined
        assert value not in provider_payload


@pytest.mark.asyncio
async def test_pii_preprocessing_failure_is_safe_and_prevents_provider_invocation(
    app_engine, owner_engine, tenant_data
) -> None:
    provider = FakeAIProvider()
    result = await _gateway(
        app_engine,
        provider,
        policy=_required_pii_policy(),
        protection=AIProtectionService(detector=BrokenDetector()),
    ).execute(context=_context(tenant_data), request=_request(PROMPT_CANARY))

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PII_PROTECTION_FAILED
    assert provider.requests == []
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.policy_allowed is True
    assert execution.pii_protection_succeeded is False
    assert execution.output_hash is None
    assert PROMPT_CANARY not in _database_text(owner_engine, result.execution_id)


@pytest.mark.parametrize(
    "category",
    [
        AIErrorCategory.TIMEOUT,
        AIErrorCategory.RATE_LIMITED,
        AIErrorCategory.PROVIDER_AUTHENTICATION_ERROR,
    ],
)
@pytest.mark.asyncio
async def test_provider_failures_are_normalized_and_raw_diagnostics_are_not_persisted(
    app_engine, owner_engine, tenant_data, category
) -> None:  # type: ignore[no-untyped-def]
    provider = FailingProvider(ProviderFailure(category=category, retryable=True))

    result = await _gateway(app_engine, provider).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None and result.error.category is category
    persisted = _database_text(owner_engine, result.execution_id)
    assert PROMPT_CANARY not in persisted
    assert SECRET_CANARY not in persisted


@pytest.mark.asyncio
async def test_invalid_provider_body_records_output_validation_failure_without_body(
    app_engine, owner_engine, tenant_data
) -> None:
    raw_body = f"not-json-{OUTPUT_CANARY}"

    result = await _gateway(app_engine, FakeAIProvider(output_text=raw_body)).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.STRUCTURED_OUTPUT_INVALID
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.error_stage is not None
    assert execution.error_stage.value == "OUTPUT_VALIDATION"
    persisted = _database_text(owner_engine, result.execution_id)
    assert raw_body not in persisted
    assert OUTPUT_CANARY not in persisted


class StageFailingRecorder:
    def __init__(self, delegate, stage: str) -> None:  # type: ignore[no-untyped-def]
        self.delegate = delegate
        self.stage = stage

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        method = getattr(self.delegate, name)
        if name == self.stage:

            def fail(**kwargs):  # type: ignore[no-untyped-def]
                raise AIProvenanceError

            return fail
        return method


@pytest.mark.asyncio
async def test_provenance_start_failure_is_fail_closed_before_provider_call(
    app_engine, tenant_data
) -> None:
    provider = FakeAIProvider()
    recorder = StageFailingRecorder(
        DatabaseAIProvenanceRecorder(build_session_factory(app_engine)), "start_execution"
    )

    result = await _gateway(app_engine, provider, provenance=recorder).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PROVENANCE_UNAVAILABLE
    assert provider.requests == []


@pytest.mark.parametrize("stage", ["record_policy", "start_attempt"])
@pytest.mark.asyncio
async def test_pre_provider_provenance_failure_is_fail_closed(
    app_engine, tenant_data, stage
) -> None:  # type: ignore[no-untyped-def]
    provider = FakeAIProvider()
    recorder = StageFailingRecorder(
        DatabaseAIProvenanceRecorder(build_session_factory(app_engine)), stage
    )

    result = await _gateway(app_engine, provider, provenance=recorder).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PROVENANCE_UNAVAILABLE
    assert provider.requests == []


@pytest.mark.asyncio
async def test_provider_success_with_finalization_failure_is_not_reported_as_success(
    app_engine, owner_engine, tenant_data
) -> None:
    provider = FakeAIProvider(output_text=json.dumps({"summary": OUTPUT_CANARY}))
    recorder = StageFailingRecorder(
        DatabaseAIProvenanceRecorder(build_session_factory(app_engine)), "finalize_execution"
    )

    result = await _gateway(app_engine, provider, provenance=recorder).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.PROVENANCE_UNAVAILABLE
    assert len(provider.requests) == 1
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.status is AIProvenanceStatus.EXECUTING
    assert execution.output_hash is None
    persisted = _database_text(owner_engine, result.execution_id)
    assert OUTPUT_CANARY not in persisted and PROMPT_CANARY not in persisted


@pytest.mark.asyncio
async def test_unexpected_exception_message_is_redacted_from_logs_and_provenance(
    app_engine, owner_engine, tenant_data
) -> None:
    provider = FailingProvider(RuntimeError(f"failed with {SECRET_CANARY} and {PROMPT_CANARY}"))
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    LOGGER.addHandler(handler)
    previous = LOGGER.propagate
    LOGGER.propagate = False
    try:
        result = await _gateway(app_engine, provider).execute(
            context=_context(tenant_data), request=_request(PROMPT_CANARY)
        )
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.propagate = previous

    assert result.error is not None and result.error.category is AIErrorCategory.INTERNAL_ERROR
    combined = output.getvalue() + _database_text(owner_engine, result.execution_id)
    assert SECRET_CANARY not in combined
    assert PROMPT_CANARY not in combined


@pytest.mark.asyncio
async def test_unknown_usage_and_provider_request_id_remain_null_not_zero(
    app_engine, owner_engine, tenant_data
) -> None:
    provider = NoOptionalMetadataProvider()

    result = await _gateway(app_engine, provider).execute(
        context=_context(tenant_data), request=_request()
    )

    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
        attempt = session.scalar(
            select(AIExecutionEvent).where(
                AIExecutionEvent.execution_id == result.execution_id,
                AIExecutionEvent.event_type == AIExecutionEventType.PROVIDER_ATTEMPT_SUCCEEDED,
            )
        )
        assert attempt is not None
    assert execution.prompt_tokens is None
    assert execution.total_tokens is None
    assert execution.cost_amount is None
    assert execution.cost_complete is False
    assert attempt.prompt_tokens is None
    assert attempt.provider_request_id is None


@pytest.mark.asyncio
async def test_success_and_failure_logs_are_correlatable_and_content_free(
    app_engine, tenant_data
) -> None:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    previous_disabled = LOGGER.disabled
    previous_level = LOGGER.level
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)
    try:
        success = await _gateway(
            app_engine,
            FakeAIProvider(output_text=json.dumps({"summary": OUTPUT_CANARY})),
        ).execute(context=_context(tenant_data), request=_request(PROMPT_CANARY))
        failure = await _gateway(
            app_engine,
            FailingProvider(ProviderFailure(category=AIErrorCategory.TIMEOUT)),
        ).execute(context=_context(tenant_data), request=_request(PROMPT_CANARY))
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.disabled = previous_disabled
        LOGGER.setLevel(previous_level)

    log_text = output.getvalue()
    assert str(success.execution_id) in log_text
    assert str(failure.execution_id) in log_text
    assert SYNTHETIC_TEXT_SUMMARY_TASK.task.value in log_text
    assert "TEST_PROVIDER" in log_text
    for canary in (PROMPT_CANARY, OUTPUT_CANARY, SOURCE_CONTENT_CANARY, SECRET_CANARY):
        assert canary not in log_text


@pytest.mark.asyncio
async def test_concurrent_gateway_executions_keep_identity_and_events_isolated(
    app_engine, owner_engine, tenant_data
) -> None:
    provider = FakeAIProvider()
    gateway = _gateway(app_engine, provider)

    results = await asyncio.gather(
        *(
            gateway.execute(
                context=_context(tenant_data),
                request=_request(f"synthetic concurrent input {index}"),
            )
            for index in range(6)
        )
    )

    execution_ids = {result.execution_id for result in results}
    assert len(execution_ids) == 6
    assert len(provider.requests) == 6
    with Session(owner_engine) as session:
        executions = session.scalars(
            select(AIExecution).where(AIExecution.id.in_(execution_ids))
        ).all()
        events = session.scalars(
            select(AIExecutionEvent).where(AIExecutionEvent.execution_id.in_(execution_ids))
        ).all()
    assert {execution.id for execution in executions} == execution_ids
    assert all(execution.provider_attempt_count == 1 for execution in executions)
    assert {event.execution_id for event in events} == execution_ids


@pytest.mark.asyncio
async def test_multiple_users_and_clients_are_attributed_to_exact_execution_context(
    app_engine, owner_engine, tenant_data
) -> None:
    gateway = _gateway(app_engine, FakeAIProvider())
    contexts = (
        _context(tenant_data),
        _context(tenant_data, client=tenant_data.acme_healthcare),
        _context(
            tenant_data,
            user=tenant_data.carol,
            membership=tenant_data.carol_membership,
        ),
    )

    results = [await gateway.execute(context=context, request=_request()) for context in contexts]

    with Session(owner_engine) as session:
        executions = [session.get(AIExecution, result.execution_id) for result in results]
    assert all(execution is not None for execution in executions)
    assert [execution.client_id for execution in executions if execution is not None] == [
        tenant_data.apollo_finance.id,
        tenant_data.acme_healthcare.id,
        tenant_data.apollo_finance.id,
    ]
    assert [execution.user_id for execution in executions if execution is not None] == [
        tenant_data.alice.id,
        tenant_data.alice.id,
        tenant_data.carol.id,
    ]
