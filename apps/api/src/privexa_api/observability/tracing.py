from __future__ import annotations

import re
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Span, SpanKind

_AI_TRACER = trace.get_tracer("privexa.ai_gateway")
_DOMAIN_TRACER = trace.get_tracer("privexa.domain")
_CONFIGURED = False
_DOMAIN_SPAN_ATTRIBUTE_KEYS = frozenset(
    {
        "domain.object_type",
        "domain.operation",
        "domain.result",
        "request.id",
        "tenant.client_id",
        "tenant.firm_id",
        "trace.id",
    }
)
_DOMAIN_SPAN_NAME = re.compile(r"^domain\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_DOMAIN_OPERATION = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_DOMAIN_OBJECT_TYPE = re.compile(r"^[A-Z][A-Za-z0-9]{0,63}$")
_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
_DOMAIN_RESULTS = frozenset({"success", "rejected", "conflict", "failed", "not_found"})


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

    return _AI_TRACER.start_as_current_span(
        name,
        kind=SpanKind.INTERNAL,
        attributes={key: value for key, value in attributes.items() if value is not None},
        record_exception=False,
        set_status_on_exception=False,
    )


def domain_span(name: str, *, attributes: dict[str, Any]) -> AbstractContextManager[Span]:
    """Trace a domain operation through a fixed non-content attribute allowlist."""

    if not _DOMAIN_SPAN_NAME.fullmatch(name):
        raise ValueError("domain span name must be a stable code identifier")

    safe_attributes: dict[str, str] = {}
    for key, value in attributes.items():
        if key not in _DOMAIN_SPAN_ATTRIBUTE_KEYS or value is None:
            continue
        normalized = str(value)
        if key in {"request.id", "tenant.client_id", "tenant.firm_id"}:
            try:
                normalized = str(UUID(normalized))
            except ValueError:
                continue
        elif any(
            (
                key == "trace.id" and not _TRACE_ID.fullmatch(normalized),
                key == "domain.operation" and not _DOMAIN_OPERATION.fullmatch(normalized),
                key == "domain.object_type" and not _DOMAIN_OBJECT_TYPE.fullmatch(normalized),
                key == "domain.result" and normalized not in _DOMAIN_RESULTS,
            )
        ):
            continue
        safe_attributes[key] = normalized

    return _DOMAIN_TRACER.start_as_current_span(
        name,
        kind=SpanKind.INTERNAL,
        attributes=safe_attributes,
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
