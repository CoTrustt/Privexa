from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from privexa_api.ai_policy.contracts import (
    AIPolicyDecision,
    AIPolicyEvaluationRequest,
    AIPolicyOutcome,
    AIPolicyReasonCode,
    AIPolicyRule,
    AIPolicyRuleReference,
    AIPolicyRuntimeSnapshot,
    EffectiveAIPolicy,
    RedactionRequirement,
    ZDRRequirement,
)
from privexa_api.ai_policy.registry import AIPolicyRegistry
from privexa_api.ai_types import AITaskType


class AIPolicyEvaluator:
    def __init__(self, registry: AIPolicyRegistry) -> None:
        self._registry = registry

    @property
    def registered_tasks(self) -> frozenset[AITaskType]:
        return self._registry.registered_tasks()

    def evaluate(
        self,
        *,
        request: AIPolicyEvaluationRequest,
        runtime: AIPolicyRuntimeSnapshot,
    ) -> AIPolicyDecision:
        context = request.context
        if not self._registry.has_task(request.task):
            return self._deny(request, AIPolicyReasonCode.UNKNOWN_TASK)
        if (
            request.required_scope is None
            or context.authorization_scope is not request.required_scope
        ):
            return self._deny(request, AIPolicyReasonCode.INVALID_CONTEXT)
        if request.required_permission is None or not context.has_capability(
            request.required_permission
        ):
            return self._deny(request, AIPolicyReasonCode.INVALID_CONTEXT)
        if runtime.global_enabled is None or runtime.task_enabled is None:
            return self._deny(
                request,
                AIPolicyReasonCode.NO_APPLICABLE_RULE,
                extra_references=runtime.control_references,
            )
        if not runtime.global_enabled:
            return self._deny(
                request,
                AIPolicyReasonCode.GLOBAL_DISABLED,
                extra_references=runtime.control_references,
            )
        if not runtime.task_enabled:
            return self._deny(
                request,
                AIPolicyReasonCode.TASK_DISABLED,
                extra_references=runtime.control_references,
            )

        baseline = self._registry.applicable(
            task=request.task,
            sensitivity=context.effective_sensitivity,
        )
        if baseline is None:
            return self._deny(
                request,
                AIPolicyReasonCode.NO_APPLICABLE_RULE,
                extra_references=runtime.control_references,
            )
        rules = (*baseline, *runtime.override_rules)
        if any(rule.constraints.enabled is False for rule in runtime.override_rules):
            return self._deny(
                request,
                AIPolicyReasonCode.TENANT_RESTRICTED,
                rules=rules,
                extra_references=runtime.control_references,
            )

        effective = _merge_rules(rules)
        if effective is None:
            reason = _empty_intersection_reason(rules)
            return self._deny(
                request,
                reason,
                rules=rules,
                extra_references=runtime.control_references,
            )
        if not request.requested_agent_authorities.issubset(effective.allowed_agent_authorities):
            return self._deny(
                request,
                AIPolicyReasonCode.AUTHORITY_DENIED,
                rules=rules,
                extra_references=runtime.control_references,
            )
        if (
            request.requested_max_output_tokens is not None
            and request.requested_max_output_tokens > effective.max_output_tokens
        ) or (
            request.requested_timeout_seconds is not None
            and request.requested_timeout_seconds > effective.timeout_seconds
        ):
            return self._deny(
                request,
                AIPolicyReasonCode.BUDGET_EXCEEDED,
                rules=rules,
                extra_references=runtime.control_references,
            )

        if request.requested_max_output_tokens is not None:
            effective = effective.model_copy(
                update={"max_output_tokens": request.requested_max_output_tokens}
            )
        if request.requested_timeout_seconds is not None:
            effective = effective.model_copy(
                update={"timeout_seconds": request.requested_timeout_seconds}
            )
        return self._allow(
            request,
            effective,
            rules=rules,
            extra_references=runtime.control_references,
        )

    def configuration_denied(
        self,
        request: AIPolicyEvaluationRequest,
    ) -> AIPolicyDecision:
        return self._deny(request, AIPolicyReasonCode.CONFIGURATION_INVALID)

    def _allow(
        self,
        request: AIPolicyEvaluationRequest,
        effective: EffectiveAIPolicy,
        *,
        rules: Iterable[AIPolicyRule],
        extra_references: tuple[AIPolicyRuleReference, ...],
    ) -> AIPolicyDecision:
        references = _references(rules, extra_references)
        policy_hash = _effective_hash(self._registry.configuration_hash, references)
        fingerprint = _decision_fingerprint(
            request=request,
            reason=AIPolicyReasonCode.ALLOWED,
            policy_hash=policy_hash,
            effective=effective,
        )
        return AIPolicyDecision(
            decision_id=uuid4(),
            decision=AIPolicyOutcome.ALLOW,
            reason_code=AIPolicyReasonCode.ALLOWED,
            policy_version=f"{self._registry.version}:{policy_hash[:12]}",
            policy_hash=policy_hash,
            decision_fingerprint=fingerprint,
            evaluated_at=datetime.now(UTC),
            task=request.task,
            task_version=request.task_version,
            firm_id=request.context.firm_id,
            client_id=request.context.client_id,
            sensitivity=request.context.effective_sensitivity,
            rule_references=references,
            effective_policy=effective,
        )

    def _deny(
        self,
        request: AIPolicyEvaluationRequest,
        reason: AIPolicyReasonCode,
        *,
        rules: Iterable[AIPolicyRule] = (),
        extra_references: tuple[AIPolicyRuleReference, ...] = (),
    ) -> AIPolicyDecision:
        references = _references(rules, extra_references)
        policy_hash = _effective_hash(self._registry.configuration_hash, references)
        return AIPolicyDecision(
            decision_id=uuid4(),
            decision=AIPolicyOutcome.DENY,
            reason_code=reason,
            policy_version=f"{self._registry.version}:{policy_hash[:12]}",
            policy_hash=policy_hash,
            decision_fingerprint=_decision_fingerprint(
                request=request,
                reason=reason,
                policy_hash=policy_hash,
                effective=None,
            ),
            evaluated_at=datetime.now(UTC),
            task=request.task if self._registry.has_task(request.task) else None,
            task_version=request.task_version,
            firm_id=request.context.firm_id,
            client_id=request.context.client_id,
            sensitivity=request.context.effective_sensitivity,
            rule_references=references,
        )


def _merge_rules(rules: Iterable[AIPolicyRule]) -> EffectiveAIPolicy | None:
    constraints = [rule.constraints for rule in rules]
    provider_sets = [
        value.allowed_provider_classes for value in constraints if value.allowed_provider_classes
    ]
    model_sets = [
        value.allowed_model_classes for value in constraints if value.allowed_model_classes
    ]
    input_limits = [value.max_input_tokens for value in constraints if value.max_input_tokens]
    output_limits = [value.max_output_tokens for value in constraints if value.max_output_tokens]
    costs = [value.max_cost_usd for value in constraints if value.max_cost_usd]
    timeouts = [value.timeout_seconds for value in constraints if value.timeout_seconds]
    zdr = [value.zdr_requirement for value in constraints if value.zdr_requirement]
    redaction = [
        value.redaction_requirement for value in constraints if value.redaction_requirement
    ]
    protection_profiles = [
        value.protection_profile for value in constraints if value.protection_profile
    ]
    fallbacks = [value.fallback_policy for value in constraints if value.fallback_policy]
    authority_sets = [
        value.allowed_agent_authorities
        for value in constraints
        if value.allowed_agent_authorities is not None
    ]
    if not all(
        (
            provider_sets,
            model_sets,
            input_limits,
            output_limits,
            costs,
            timeouts,
            zdr,
            redaction,
            protection_profiles,
            fallbacks,
            authority_sets,
        )
    ):
        return None
    providers = frozenset.intersection(*provider_sets)
    models = frozenset.intersection(*model_sets)
    if not providers or not models:
        return None
    return EffectiveAIPolicy(
        allowed_provider_classes=providers,
        allowed_model_classes=models,
        zdr_requirement=(
            ZDRRequirement.REQUIRED
            if ZDRRequirement.REQUIRED in zdr
            else ZDRRequirement.NOT_REQUIRED
        ),
        redaction_requirement=(
            RedactionRequirement.REQUIRED
            if RedactionRequirement.REQUIRED in redaction
            else RedactionRequirement.NOT_REQUIRED
        ),
        protection_profile=max(
            protection_profiles,
            key=lambda value: value.restrictiveness,
        ),
        max_input_tokens=min(input_limits),
        max_output_tokens=min(output_limits),
        max_cost_usd=min(costs, default=Decimal("0")),
        timeout_seconds=min(timeouts),
        fallback_policy=max(fallbacks, key=lambda value: value.restrictiveness),
        allowed_agent_authorities=frozenset.intersection(*authority_sets),
    )


def _empty_intersection_reason(rules: Iterable[AIPolicyRule]) -> AIPolicyReasonCode:
    constraints = [rule.constraints for rule in rules]
    providers = [
        value.allowed_provider_classes for value in constraints if value.allowed_provider_classes
    ]
    if providers and not frozenset.intersection(*providers):
        return AIPolicyReasonCode.PROVIDER_CLASS_UNAVAILABLE
    models = [value.allowed_model_classes for value in constraints if value.allowed_model_classes]
    if models and not frozenset.intersection(*models):
        return AIPolicyReasonCode.MODEL_CLASS_UNAVAILABLE
    return AIPolicyReasonCode.CONFIGURATION_INVALID


def _references(
    rules: Iterable[AIPolicyRule],
    extra: tuple[AIPolicyRuleReference, ...],
) -> tuple[AIPolicyRuleReference, ...]:
    values = [
        AIPolicyRuleReference(
            rule_id=rule.rule_id,
            revision=rule.revision,
            content_hash=rule.content_hash,
        )
        for rule in rules
    ]
    values.extend(extra)
    return tuple(sorted(values, key=lambda value: (value.rule_id, value.revision)))


def _effective_hash(
    registry_hash: str,
    references: tuple[AIPolicyRuleReference, ...],
) -> str:
    payload = {
        "registry_hash": registry_hash,
        "rules": [reference.model_dump(mode="json") for reference in references],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _decision_fingerprint(
    *,
    request: AIPolicyEvaluationRequest,
    reason: AIPolicyReasonCode,
    policy_hash: str,
    effective: EffectiveAIPolicy | None,
) -> str:
    payload = {
        "firm_id": str(request.context.firm_id),
        "client_id": str(request.context.client_id) if request.context.client_id else None,
        "task": request.task.value if isinstance(request.task, AITaskType) else None,
        "task_version": request.task_version,
        "sensitivity": request.context.effective_sensitivity.value,
        "reason": reason.value,
        "policy_hash": policy_hash,
        "effective": effective.model_dump(mode="json") if effective is not None else None,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
