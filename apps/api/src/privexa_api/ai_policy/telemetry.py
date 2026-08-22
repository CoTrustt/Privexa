from __future__ import annotations

import json
import logging
from time import monotonic

from privexa_api.ai_policy.contracts import AIPolicyDecision

LOGGER = logging.getLogger("privexa.ai_policy")
_HANDLER_NAME = "privexa-ai-policy-json"


def configure_ai_policy_logging() -> None:
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(handler.get_name() == _HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)


class AIPolicyTelemetry:
    @staticmethod
    def start() -> float:
        return monotonic()

    def evaluated(self, decision: AIPolicyDecision, *, started_clock: float) -> None:
        effective = decision.effective_policy
        payload: dict[str, object | None] = {
            "event": "ai.policy.evaluated",
            "decision_id": str(decision.decision_id),
            "decision": decision.decision.value,
            "reason_code": decision.reason_code.value,
            "policy_version": decision.policy_version,
            "policy_hash": decision.policy_hash,
            "decision_fingerprint": decision.decision_fingerprint,
            "task": decision.task.value if decision.task is not None else None,
            "task_version": decision.task_version,
            "firm_id": str(decision.firm_id) if decision.firm_id is not None else None,
            "client_id": str(decision.client_id) if decision.client_id is not None else None,
            "sensitivity": decision.sensitivity.value if decision.sensitivity is not None else None,
            "rule_ids": [reference.rule_id for reference in decision.rule_references],
            "evaluation_latency_ms": max(0, round((monotonic() - started_clock) * 1_000)),
            "provider_class_count": (
                len(effective.allowed_provider_classes) if effective is not None else 0
            ),
            "model_class_count": (
                len(effective.allowed_model_classes) if effective is not None else 0
            ),
            "zdr_requirement": effective.zdr_requirement.value if effective else None,
            "redaction_requirement": (effective.redaction_requirement.value if effective else None),
            "protection_profile": effective.protection_profile.value if effective else None,
            "fallback_policy": effective.fallback_policy.value if effective else None,
            "max_input_tokens": effective.max_input_tokens if effective else None,
            "max_output_tokens": effective.max_output_tokens if effective else None,
            "max_cost_usd": str(effective.max_cost_usd) if effective else None,
        }
        LOGGER.info(json.dumps(payload, sort_keys=True))
