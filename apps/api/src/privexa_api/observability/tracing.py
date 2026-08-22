from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, SpanKind

_TRACER = trace.get_tracer("privexa.ai_gateway")
_CONFIGURED = False


@dataclass(frozen=True, slots=True)
class TraceCorrelation:
    trace_id: str | None
    span_id: str | None
    sampled: bool | None


def configure_tracing(*, service_name: str = "privexa-api") -> None:
    """Install the minimal SDK provider once; exporters remain deployment configuration."""

    global _CONFIGURED
    if _CONFIGURED:
        return
    current = trace.get_tracer_provider()
    if current.__class__.__name__ == "ProxyTracerProvider":
        trace.set_tracer_provider(
            TracerProvider(resource=Resource.create({"service.name": service_name}))
        )
    _CONFIGURED = True


def ai_span(name: str, *, attributes: dict[str, Any]) -> AbstractContextManager[Span]:
    """Start a span using only explicitly allowlisted, non-content attributes."""

    return _TRACER.start_as_current_span(
        name,
        kind=SpanKind.INTERNAL,
        attributes={key: value for key, value in attributes.items() if value is not None},
        record_exception=False,
        set_status_on_exception=False,
    )


def current_trace_correlation() -> TraceCorrelation:
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return TraceCorrelation(trace_id=None, span_id=None, sampled=None)
    return TraceCorrelation(
        trace_id=f"{context.trace_id:032x}",
        span_id=f"{context.span_id:016x}",
        sampled=context.trace_flags.sampled,
    )
