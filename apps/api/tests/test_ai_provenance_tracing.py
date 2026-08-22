from __future__ import annotations

import json

import pytest
from fixtures.ai_gateway import FakeAIProvider
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.orm import Session
from test_ai_provenance_gateway_integration import (
    OUTPUT_CANARY,
    PROMPT_CANARY,
    SECRET_CANARY,
    CanaryDetector,
    FailingProvider,
    _context,
    _gateway,
    _request,
    _required_pii_policy,
)

from privexa_api.ai_gateway.contracts import AIExecutionStatus
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_protection.service import AIProtectionService
from privexa_api.ai_provenance.models import AIExecution
from privexa_api.observability.tracing import ai_span, configure_tracing, current_trace_correlation


def _span_text(spans) -> str:  # type: ignore[no-untyped-def]
    payload = []
    for span in spans:
        payload.append(
            {
                "name": span.name,
                "attributes": dict(span.attributes or {}),
                "events": [dict(event.attributes or {}) for event in span.events],
                "status": span.status.description,
            }
        )
    return json.dumps(payload, sort_keys=True, default=str)


def _exporter() -> InMemorySpanExporter:
    configure_tracing(service_name="privexa-api-test")
    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.mark.asyncio
async def test_gateway_spans_correlate_with_provenance_and_exclude_content(
    app_engine, owner_engine, tenant_data
) -> None:
    exporter = _exporter()
    provider = FakeAIProvider(output_text=json.dumps({"summary": OUTPUT_CANARY}))
    with ai_span("test.request", attributes={}):
        expected_trace_id = current_trace_correlation().trace_id
        result = await _gateway(app_engine, provider).execute(
            context=_context(tenant_data), request=_request(PROMPT_CANARY)
        )

    spans = exporter.get_finished_spans()
    execution_span = next(span for span in spans if span.name == "ai.execution")
    assert execution_span.attributes["ai.execution.id"] == str(result.execution_id)
    assert execution_span.attributes["ai.execution.status"] == AIExecutionStatus.SUCCEEDED.value
    assert execution_span.attributes["ai.availability.decision"] == "ALLOW"
    assert {
        "ai.policy.evaluate",
        "ai.protection.apply",
        "ai.route.select",
        "ai.provider.attempt",
    }.issubset({span.name for span in spans})
    attempt_span = next(span for span in spans if span.name == "ai.provider.attempt")
    assert attempt_span.attributes["ai.circuit.state"] == "CLOSED"
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.trace_id == expected_trace_id
    assert PROMPT_CANARY not in _span_text(spans)
    assert OUTPUT_CANARY not in _span_text(spans)


@pytest.mark.asyncio
async def test_raw_exception_message_is_not_recorded_as_otel_exception_event(
    app_engine, tenant_data
) -> None:
    exporter = _exporter()
    provider = FailingProvider(RuntimeError(f"{SECRET_CANARY} {PROMPT_CANARY}"))

    result = await _gateway(app_engine, provider).execute(
        context=_context(tenant_data), request=_request(PROMPT_CANARY)
    )

    assert result.error is not None
    assert result.error.category is AIErrorCategory.INTERNAL_ERROR
    trace_text = _span_text(exporter.get_finished_spans())
    assert SECRET_CANARY not in trace_text
    assert PROMPT_CANARY not in trace_text


@pytest.mark.asyncio
async def test_pii_values_never_enter_trace_attributes_or_events(app_engine, tenant_data) -> None:
    exporter = _exporter()
    detector = CanaryDetector()
    content = " ".join(detector.values.values())

    result = await _gateway(
        app_engine,
        FakeAIProvider(),
        policy=_required_pii_policy(),
        protection=AIProtectionService(detector=detector),
    ).execute(context=_context(tenant_data), request=_request(content))

    assert result.status is AIExecutionStatus.SUCCEEDED
    trace_text = _span_text(exporter.get_finished_spans())
    for value in detector.values.values():
        assert value not in trace_text


@pytest.mark.asyncio
async def test_policy_denial_is_trace_correlated_without_provider_span(
    app_engine, owner_engine, tenant_data
) -> None:
    exporter = _exporter()
    provider = FakeAIProvider()
    with ai_span("test.denied.request", attributes={}):
        expected_trace_id = current_trace_correlation().trace_id
        result = await _gateway(app_engine, provider, enabled=False).execute(
            context=_context(tenant_data), request=_request(PROMPT_CANARY)
        )

    spans = exporter.get_finished_spans()
    assert result.status is AIExecutionStatus.REJECTED
    assert provider.requests == []
    assert "ai.provider.attempt" not in {span.name for span in spans}
    execution_span = next(span for span in spans if span.name == "ai.execution")
    assert execution_span.attributes["ai.execution.status"] == AIExecutionStatus.REJECTED.value
    with Session(owner_engine) as session:
        execution = session.get(AIExecution, result.execution_id)
        assert execution is not None
    assert execution.trace_id == expected_trace_id
    assert PROMPT_CANARY not in _span_text(spans)
