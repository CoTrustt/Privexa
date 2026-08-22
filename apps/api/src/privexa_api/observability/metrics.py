from __future__ import annotations

from collections.abc import Mapping

from opentelemetry import metrics

_METER = metrics.get_meter("privexa.ai_gateway")

AI_GATEWAY_REQUESTS = _METER.create_counter(
    "ai_gateway_requests_total",
    description="AI Gateway execution attempts by task and terminal status.",
)
AI_GATEWAY_BLOCKED = _METER.create_counter(
    "ai_gateway_blocked_total",
    description="AI executions prevented before successful completion.",
)
AI_PROVIDER_FAILURES = _METER.create_counter(
    "ai_provider_failures_total",
    description="Normalized provider execution failures.",
)
AI_PROVIDER_TIMEOUTS = _METER.create_counter(
    "ai_provider_timeouts_total",
    description="Normalized provider timeouts.",
)
AI_CIRCUIT_OPEN = _METER.create_counter(
    "ai_circuit_open_total",
    description="Executions prevented by an open provider circuit.",
)
AI_RESULT_INTERRUPTION = _METER.create_counter(
    "ai_agent_interruptions_total",
    description="AI results discarded after execution authority was revoked.",
)


def record_ai_event(event: str, fields: Mapping[str, object | None]) -> None:
    """Record only bounded operational dimensions; never tenant or content identifiers."""

    attributes = _attributes(fields)
    if event in {"ai.execution.completed", "ai.execution.denied", "ai.execution.failed"}:
        AI_GATEWAY_REQUESTS.add(1, attributes)
    if event == "ai.execution.denied":
        AI_GATEWAY_BLOCKED.add(1, attributes)
    if event == "ai.execution.failed" and fields.get("provider") is not None:
        AI_PROVIDER_FAILURES.add(1, attributes)
    if fields.get("error_category") == "TIMEOUT":
        AI_PROVIDER_TIMEOUTS.add(1, attributes)
    if fields.get("error_category") == "CIRCUIT_OPEN":
        AI_CIRCUIT_OPEN.add(1, attributes)
    if fields.get("error_category") == "RESULT_AUTHORITY_REVOKED":
        AI_RESULT_INTERRUPTION.add(1, attributes)


def _attributes(fields: Mapping[str, object | None]) -> dict[str, str]:
    allowed = {
        "task": "ai.task_type",
        "status": "ai.status",
        "error_category": "ai.failure_category",
        "provider": "ai.provider_class",
    }
    return {
        target: str(fields[source])
        for source, target in allowed.items()
        if fields.get(source) is not None
    }
