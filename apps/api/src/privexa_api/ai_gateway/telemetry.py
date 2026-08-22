from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from uuid import UUID

from privexa_api.ai_gateway.contracts import AIUsage
from privexa_api.ai_gateway.errors import AIErrorCategory, ProviderFailure
from privexa_api.observability.metrics import record_ai_event
from privexa_api.security.execution_context import ExecutionContext

LOGGER = logging.getLogger("privexa.ai_gateway")
_HANDLER_NAME = "privexa-ai-gateway-json"


def configure_ai_gateway_logging() -> None:
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


class AIExecutionTelemetry:
    def emit(
        self,
        event: str,
        *,
        execution_id: UUID,
        context: ExecutionContext | None,
        fields: Mapping[str, object | None],
    ) -> None:
        payload: dict[str, object | None] = {
            "event": event,
            "execution_id": str(execution_id),
        }
        if context is not None:
            payload.update(context.safe_logging_fields())
            payload["sensitivity"] = context.effective_sensitivity.value
        payload.update(fields)
        LOGGER.info(json.dumps(payload, sort_keys=True, default=str))
        record_ai_event(event, fields)

    def unexpected_failure(
        self,
        *,
        execution_id: UUID,
        context: ExecutionContext | None,
        fields: Mapping[str, object | None],
        error: Exception,
    ) -> None:
        payload: dict[str, object | None] = {
            "event": "ai.execution.failed",
            "execution_id": str(execution_id),
            "exception_type": type(error).__name__,
            **fields,
        }
        if context is not None:
            payload.update(context.safe_logging_fields())
            payload["sensitivity"] = context.effective_sensitivity.value
        sanitized_error = RuntimeError("internal exception details redacted")
        LOGGER.error(
            json.dumps(payload, sort_keys=True, default=str),
            exc_info=(RuntimeError, sanitized_error, error.__traceback__),
        )
        record_ai_event("ai.execution.failed", fields)

    def provenance_failure(
        self,
        *,
        execution_id: UUID,
        context: ExecutionContext | None,
        stage: str,
    ) -> None:
        payload: dict[str, object | None] = {
            "event": "ai.provenance.failed",
            "execution_id": str(execution_id),
            "error_category": AIErrorCategory.PROVENANCE_UNAVAILABLE.value,
            "stage": stage,
        }
        if context is not None:
            payload.update(context.safe_logging_fields())
            payload["sensitivity"] = context.effective_sensitivity.value
        LOGGER.error(json.dumps(payload, sort_keys=True, default=str))


def usage_logging_fields(usage: AIUsage | None) -> dict[str, object | None]:
    if usage is None:
        return {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "cached_tokens": None,
            "reasoning_tokens": None,
            "reported_cost": None,
            "cost_currency": None,
        }
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "cached_tokens": usage.cached_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "reported_cost": usage.reported_cost,
        "cost_currency": usage.cost_currency,
    }


def provider_failure_logging_fields(error: ProviderFailure) -> dict[str, object | None]:
    return {
        "error_category": error.category.value,
        "provider_http_status": error.provider_http_status,
        "provider_error_category": error.provider_error_category,
        "retryable": error.retryable,
    }


def error_logging_fields(category: AIErrorCategory) -> dict[str, object | None]:
    return {"error_category": category.value, "retryable": False}
