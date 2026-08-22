from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal
from types import MappingProxyType

from privexa_api.ai_policy.contracts import (
    AgentAuthority,
    AIFallbackPolicy,
    AIModelClass,
    AIPolicyConstraints,
    AIPolicyRule,
    AIProtectionProfileId,
    AIProviderClass,
    RedactionRequirement,
    ZDRRequirement,
)
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel

BASELINE_POLICY_VERSION = "build0-v1"


def _canonicalize(value: object) -> object:
    if isinstance(value, dict):
        return {key: _canonicalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True))
    return value


def _rule(
    *,
    rule_id: str,
    task: AITaskType | None = None,
    sensitivity: SensitivityLevel | None = None,
    constraints: AIPolicyConstraints,
) -> AIPolicyRule:
    canonical = {
        "rule_id": rule_id,
        "revision": 1,
        "task": task.value if task is not None else None,
        "sensitivity": sensitivity.value if sensitivity is not None else None,
        "constraints": _canonicalize(constraints.model_dump(mode="json", exclude_none=True)),
    }
    content_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return AIPolicyRule(
        rule_id=rule_id,
        revision=1,
        task=task,
        sensitivity=sensitivity,
        constraints=constraints,
        content_hash=content_hash,
    )


GLOBAL_SECURITY_CEILING = _rule(
    rule_id="baseline.global",
    constraints=AIPolicyConstraints(
        enabled=True,
        allowed_provider_classes=frozenset(
            {
                AIProviderClass.ENTERPRISE_APPROVED,
                AIProviderClass.ZDR_APPROVED,
            }
        ),
        allowed_model_classes=frozenset(
            {
                AIModelClass.GENERAL_APPROVED,
                AIModelClass.RESTRICTED_DATA_APPROVED,
            }
        ),
        zdr_requirement=ZDRRequirement.REQUIRED,
        redaction_requirement=RedactionRequirement.NOT_REQUIRED,
        protection_profile=AIProtectionProfileId.NONE,
        max_input_tokens=8_192,
        max_output_tokens=4_096,
        max_cost_usd=Decimal("0.50"),
        timeout_seconds=20.0,
        fallback_policy=AIFallbackPolicy.NO_FALLBACK,
        allowed_agent_authorities=frozenset(
            {
                AgentAuthority.READ_AUTHORISED_CONTEXT,
                AgentAuthority.PREPARE_PROPOSED_OUTPUT,
            }
        ),
    ),
)

SENSITIVITY_RULES = MappingProxyType(
    {
        SensitivityLevel.STANDARD: _rule(
            rule_id="baseline.sensitivity.standard",
            sensitivity=SensitivityLevel.STANDARD,
            constraints=AIPolicyConstraints(
                allowed_provider_classes=frozenset(
                    {
                        AIProviderClass.ENTERPRISE_APPROVED,
                        AIProviderClass.ZDR_APPROVED,
                    }
                ),
                allowed_model_classes=frozenset({AIModelClass.GENERAL_APPROVED}),
                max_input_tokens=8_192,
                max_output_tokens=2_048,
                max_cost_usd=Decimal("0.25"),
            ),
        ),
        SensitivityLevel.SENSITIVE: _rule(
            rule_id="baseline.sensitivity.sensitive",
            sensitivity=SensitivityLevel.SENSITIVE,
            constraints=AIPolicyConstraints(
                allowed_provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
                allowed_model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
                zdr_requirement=ZDRRequirement.REQUIRED,
                redaction_requirement=RedactionRequirement.REQUIRED,
                protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
                max_input_tokens=4_096,
                max_output_tokens=1_024,
                max_cost_usd=Decimal("0.20"),
            ),
        ),
        SensitivityLevel.RESTRICTED: _rule(
            rule_id="baseline.sensitivity.restricted",
            sensitivity=SensitivityLevel.RESTRICTED,
            constraints=AIPolicyConstraints(
                allowed_provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
                allowed_model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
                zdr_requirement=ZDRRequirement.REQUIRED,
                redaction_requirement=RedactionRequirement.REQUIRED,
                protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
                max_input_tokens=2_048,
                max_output_tokens=512,
                max_cost_usd=Decimal("0.10"),
            ),
        ),
    }
)

TASK_RULES = MappingProxyType(
    {
        (AITaskType.SYNTHETIC_TEXT_SUMMARY, SensitivityLevel.STANDARD): _rule(
            rule_id="task.synthetic_text_summary.standard",
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
            sensitivity=SensitivityLevel.STANDARD,
            constraints=AIPolicyConstraints(
                enabled=True,
                allowed_provider_classes=frozenset(
                    {
                        AIProviderClass.ENTERPRISE_APPROVED,
                        AIProviderClass.ZDR_APPROVED,
                    }
                ),
                allowed_model_classes=frozenset({AIModelClass.GENERAL_APPROVED}),
                zdr_requirement=ZDRRequirement.REQUIRED,
                redaction_requirement=RedactionRequirement.NOT_REQUIRED,
                protection_profile=AIProtectionProfileId.NONE,
                max_input_tokens=4_096,
                max_output_tokens=128,
                max_cost_usd=Decimal("0.05"),
                timeout_seconds=20.0,
                fallback_policy=AIFallbackPolicy.NO_FALLBACK,
                allowed_agent_authorities=frozenset(
                    {
                        AgentAuthority.READ_AUTHORISED_CONTEXT,
                        AgentAuthority.PREPARE_PROPOSED_OUTPUT,
                    }
                ),
            ),
        ),
        (AITaskType.PREPARE_WORK_NOTE, SensitivityLevel.SENSITIVE): _rule(
            rule_id="task.ai.prepare_work_note.sensitive",
            task=AITaskType.PREPARE_WORK_NOTE,
            sensitivity=SensitivityLevel.SENSITIVE,
            constraints=AIPolicyConstraints(
                enabled=True,
                allowed_provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
                allowed_model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED}),
                zdr_requirement=ZDRRequirement.REQUIRED,
                redaction_requirement=RedactionRequirement.REQUIRED,
                protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
                max_input_tokens=1_500,
                max_output_tokens=400,
                max_cost_usd=Decimal("0.05"),
                timeout_seconds=20.0,
                fallback_policy=AIFallbackPolicy.NO_FALLBACK,
                allowed_agent_authorities=frozenset(
                    {
                        AgentAuthority.READ_AUTHORISED_CONTEXT,
                        AgentAuthority.PREPARE_PROPOSED_OUTPUT,
                    }
                ),
            ),
        ),
    }
)


class AIPolicyRegistry:
    def __init__(
        self,
        *,
        version: str,
        global_rule: AIPolicyRule,
        sensitivity_rules: dict[SensitivityLevel, AIPolicyRule],
        task_rules: dict[tuple[AITaskType, SensitivityLevel], AIPolicyRule],
    ) -> None:
        if not version:
            raise ValueError("AI policy version is required")
        if set(sensitivity_rules) != set(SensitivityLevel):
            raise ValueError("AI policy requires one baseline rule for every sensitivity")
        if not task_rules:
            raise ValueError("AI policy requires at least one explicit task rule")
        self.version = version
        self.global_rule = global_rule
        self.sensitivity_rules = MappingProxyType(dict(sensitivity_rules))
        self.task_rules = MappingProxyType(dict(task_rules))
        self.configuration_hash = _rules_hash(self.all_rules())

    def all_rules(self) -> tuple[AIPolicyRule, ...]:
        return (
            self.global_rule,
            *self.sensitivity_rules.values(),
            *self.task_rules.values(),
        )

    def has_task(self, task: object) -> bool:
        return isinstance(task, AITaskType) and any(key[0] is task for key in self.task_rules)

    def registered_tasks(self) -> frozenset[AITaskType]:
        return frozenset(key[0] for key in self.task_rules)

    def applicable(
        self,
        *,
        task: AITaskType,
        sensitivity: SensitivityLevel,
    ) -> tuple[AIPolicyRule, ...] | None:
        sensitivity_rule = self.sensitivity_rules.get(sensitivity)
        task_rule = self.task_rules.get((task, sensitivity))
        if sensitivity_rule is None or task_rule is None:
            return None
        return self.global_rule, sensitivity_rule, task_rule


def _rules_hash(rules: Iterable[AIPolicyRule]) -> str:
    canonical = [
        _canonicalize(rule.model_dump(mode="json"))
        for rule in sorted(rules, key=lambda value: (value.rule_id, value.revision))
    ]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_policy_registry(
    *,
    max_cost_usd: Decimal | None = None,
    max_timeout_seconds: float | None = None,
) -> AIPolicyRegistry:
    global_rule = GLOBAL_SECURITY_CEILING
    updates: dict[str, object] = {}
    if max_cost_usd is not None:
        updates["max_cost_usd"] = min(
            global_rule.constraints.max_cost_usd or max_cost_usd,
            max_cost_usd,
        )
    if max_timeout_seconds is not None:
        updates["timeout_seconds"] = min(
            global_rule.constraints.timeout_seconds or max_timeout_seconds,
            max_timeout_seconds,
        )
    if updates:
        global_rule = _rule(
            rule_id=global_rule.rule_id,
            constraints=global_rule.constraints.model_copy(update=updates),
        )
    return AIPolicyRegistry(
        version=BASELINE_POLICY_VERSION,
        global_rule=global_rule,
        sensitivity_rules=dict(SENSITIVITY_RULES),
        task_rules=dict(TASK_RULES),
    )
