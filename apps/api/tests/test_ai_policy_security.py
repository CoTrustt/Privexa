from __future__ import annotations

import ast
import hashlib
import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from fixtures.ai_gateway import trusted_ai_context
from pydantic import ValidationError

from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.ai_policy.contracts import (
    BUILD0_AGENT_AUTHORITY_CEILING,
    AgentAuthority,
    AIFallbackPolicy,
    AIModelClass,
    AIPolicyConstraints,
    AIPolicyEvaluationRequest,
    AIPolicyOutcome,
    AIPolicyReasonCode,
    AIPolicyRule,
    AIProtectionProfileId,
    AIProviderClass,
    RedactionRequirement,
    ZDRRequirement,
)
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import AIPolicyRegistry, build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_policy.telemetry import LOGGER, AIPolicyTelemetry
from privexa_api.ai_types import AITaskType
from privexa_api.security.enums import SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext

pytestmark = pytest.mark.security
API_ROOT = Path(__file__).resolve().parents[1]
POLICY_SOURCE_ROOT = API_ROOT / "src" / "privexa_api" / "ai_policy"


def _rule(
    *,
    rule_id: str,
    constraints: AIPolicyConstraints,
    task: AITaskType | None = None,
    sensitivity: SensitivityLevel | None = None,
    revision: int = 1,
) -> AIPolicyRule:
    payload = {
        "rule_id": rule_id,
        "revision": revision,
        "task": task.value if task is not None else None,
        "sensitivity": sensitivity.value if sensitivity is not None else None,
        "constraints": constraints.model_dump(mode="json", exclude_none=True),
    }
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AIPolicyRule(
        rule_id=rule_id,
        revision=revision,
        task=task,
        sensitivity=sensitivity,
        constraints=constraints,
        content_hash=content_hash,
    )


def _engine(
    *,
    registry: AIPolicyRegistry | None = None,
    repository: StaticAIPolicyRepository | None = None,
    enabled: bool = True,
    telemetry: AIPolicyTelemetry | None = None,
) -> AIPolicyEngine:
    policy_registry = registry or build_policy_registry()
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(policy_registry),
        repository=repository or StaticAIPolicyRepository(),
        deployment_enabled=enabled,
        telemetry=telemetry,
    )


def _request(
    *,
    sensitivity: SensitivityLevel = SensitivityLevel.STANDARD,
    authorities: frozenset[AgentAuthority] = BUILD0_AGENT_AUTHORITY_CEILING,
) -> AIPolicyEvaluationRequest:
    return AIPolicyEvaluationRequest(
        context=trusted_ai_context(sensitivity=sensitivity),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        task_version="1",
        required_scope=AuthorizationScope.CLIENT,
        required_permission=Permission.CLIENT_READ,
        requested_agent_authorities=authorities,
    )


def _registry_for_all_sensitivities() -> AIPolicyRegistry:
    baseline = build_policy_registry()
    standard_task = next(iter(baseline.task_rules.values()))
    broad_task_constraints = standard_task.constraints.model_copy(
        update={
            "allowed_provider_classes": frozenset(
                {
                    AIProviderClass.ENTERPRISE_APPROVED,
                    AIProviderClass.ZDR_APPROVED,
                }
            ),
            "allowed_model_classes": frozenset(set(AIModelClass)),
            "max_input_tokens": 8_192,
            "max_output_tokens": 4_096,
            "max_cost_usd": Decimal("0.50"),
        }
    )
    task_rules = {
        (AITaskType.SYNTHETIC_TEXT_SUMMARY, sensitivity): _rule(
            rule_id=f"task.synthetic_text_summary.{sensitivity.value.lower()}",
            task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
            sensitivity=sensitivity,
            constraints=broad_task_constraints,
        )
        for sensitivity in SensitivityLevel
    }
    return AIPolicyRegistry(
        version="test-all-sensitivity-v1",
        global_rule=baseline.global_rule,
        sensitivity_rules=dict(baseline.sensitivity_rules),
        task_rules=task_rules,
    )


@contextmanager
def _captured_policy_logs() -> Iterator[io.StringIO]:
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    previous_level = LOGGER.level
    previous_disabled = LOGGER.disabled
    LOGGER.disabled = False
    LOGGER.setLevel(logging.INFO)
    LOGGER.addHandler(handler)
    try:
        yield output
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(previous_level)
        LOGGER.disabled = previous_disabled


def test_policy_evaluation_is_semantically_deterministic_across_100_runs() -> None:
    request = _request()
    decisions = [_engine().evaluate(session=None, request=request) for _ in range(100)]
    semantic_results = {
        (
            decision.decision,
            decision.reason_code,
            decision.policy_version,
            decision.policy_hash,
            decision.decision_fingerprint,
            decision.effective_policy,
            decision.rule_references,
        )
        for decision in decisions
    }
    assert len({decision.decision_id for decision in decisions}) == 100
    assert len(semantic_results) == 1


def test_policy_package_has_no_gateway_provider_or_network_dependency() -> None:
    forbidden_roots = {
        "anthropic",
        "httpx",
        "openai",
        "openrouter",
        "privexa_api.ai_gateway",
        "requests",
    }
    violations: list[str] = []
    for source_file in POLICY_SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                if any(module == root or module.startswith(f"{root}.") for root in forbidden_roots):
                    violations.append(f"{source_file.name}:{node.lineno}:{module}")
    assert violations == []


def test_unknown_task_denies_with_stable_reason_without_loading_repository() -> None:
    class FailOnLoadRepository(StaticAIPolicyRepository):
        def load(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            raise AssertionError("unknown task must deny before repository/provider work")

    known_request = _request()
    request = AIPolicyEvaluationRequest.model_construct(
        **{
            **known_request.__dict__,
            "task": "unregistered_task",
        }
    )
    decision = _engine(repository=FailOnLoadRepository()).evaluate(
        session=None,
        request=request,
    )
    assert decision.decision is AIPolicyOutcome.DENY
    assert decision.reason_code is AIPolicyReasonCode.UNKNOWN_TASK
    assert decision.task is None


@pytest.mark.parametrize("sensitivity", [SensitivityLevel.SENSITIVE, SensitivityLevel.RESTRICTED])
def test_registered_task_without_applicable_sensitivity_rule_denies(
    sensitivity: SensitivityLevel,
) -> None:
    decision = _engine().evaluate(session=None, request=_request(sensitivity=sensitivity))
    assert decision.decision is AIPolicyOutcome.DENY
    assert decision.reason_code is AIPolicyReasonCode.NO_APPLICABLE_RULE


@pytest.mark.parametrize(
    "payload",
    [
        {"max_input_tokens": 0},
        {"max_output_tokens": -1},
        {"max_cost_usd": Decimal("0")},
        {"timeout_seconds": -0.1},
        {"allowed_provider_classes": frozenset()},
        {"allowed_model_classes": frozenset()},
        {"zdr_requirement": "OPTIONAL"},
        {"redaction_requirement": "BEST_EFFORT"},
        {"fallback_policy": "ANY_PROVIDER"},
        {"allowed_agent_authorities": frozenset({"ROOT"})},
        {"max_ouput_tokens": 100},
    ],
)
def test_malformed_policy_constraints_are_rejected_not_defaulted(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AIPolicyConstraints.model_validate(payload)


def test_policy_registry_rejects_incomplete_or_empty_configuration() -> None:
    baseline = build_policy_registry()
    with pytest.raises(ValueError, match="every sensitivity"):
        AIPolicyRegistry(
            version="invalid-v1",
            global_rule=baseline.global_rule,
            sensitivity_rules={
                SensitivityLevel.STANDARD: baseline.sensitivity_rules[SensitivityLevel.STANDARD]
            },
            task_rules=dict(baseline.task_rules),
        )
    with pytest.raises(ValueError, match="at least one explicit task"):
        AIPolicyRegistry(
            version="invalid-v1",
            global_rule=baseline.global_rule,
            sensitivity_rules=dict(baseline.sensitivity_rules),
            task_rules={},
        )


@pytest.mark.parametrize(
    "authorities",
    [
        frozenset(),
        frozenset({AgentAuthority.READ_AUTHORISED_CONTEXT}),
        frozenset({AgentAuthority.PREPARE_PROPOSED_OUTPUT}),
        BUILD0_AGENT_AUTHORITY_CEILING,
    ],
)
def test_build0_allowed_authority_combinations_can_receive_allow(
    authorities: frozenset[AgentAuthority],
) -> None:
    decision = _engine().evaluate(session=None, request=_request(authorities=authorities))
    assert decision.decision is AIPolicyOutcome.ALLOW


@pytest.mark.parametrize(
    "authority",
    sorted(set(AgentAuthority) - BUILD0_AGENT_AUTHORITY_CEILING, key=lambda value: value.value),
)
def test_every_dangerous_build0_authority_is_denied(authority: AgentAuthority) -> None:
    decision = _engine().evaluate(
        session=None,
        request=_request(authorities=frozenset({authority})),
    )
    assert decision.decision is AIPolicyOutcome.DENY
    assert decision.reason_code is AIPolicyReasonCode.AUTHORITY_DENIED


def test_mixed_safe_and_dangerous_authority_request_denies_whole_operation() -> None:
    decision = _engine().evaluate(
        session=None,
        request=_request(
            authorities=frozenset(
                {
                    AgentAuthority.READ_AUTHORISED_CONTEXT,
                    AgentAuthority.EXTERNAL_COMMUNICATION,
                }
            )
        ),
    )
    assert decision.decision is AIPolicyOutcome.DENY
    assert decision.reason_code is AIPolicyReasonCode.AUTHORITY_DENIED


def test_policy_precedence_uses_intersection_minimum_and_mandatory_controls() -> None:
    override = _rule(
        rule_id="test.tenant.restrictive",
        constraints=AIPolicyConstraints(
            allowed_provider_classes=frozenset({AIProviderClass.ZDR_APPROVED}),
            allowed_model_classes=frozenset({AIModelClass.GENERAL_APPROVED}),
            zdr_requirement=ZDRRequirement.REQUIRED,
            redaction_requirement=RedactionRequirement.REQUIRED,
            protection_profile=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
            max_input_tokens=3_000,
            max_output_tokens=64,
            max_cost_usd=Decimal("0.01"),
            timeout_seconds=5.0,
            fallback_policy=AIFallbackPolicy.NO_FALLBACK,
            allowed_agent_authorities=frozenset({AgentAuthority.READ_AUTHORISED_CONTEXT}),
        ),
    )
    decision = _engine(repository=StaticAIPolicyRepository(override_rules=(override,))).evaluate(
        session=None,
        request=_request(authorities=frozenset({AgentAuthority.READ_AUTHORISED_CONTEXT})),
    )
    policy = decision.effective_policy
    assert decision.decision is AIPolicyOutcome.ALLOW and policy is not None
    assert policy.allowed_provider_classes == frozenset({AIProviderClass.ZDR_APPROVED})
    assert policy.allowed_model_classes == frozenset({AIModelClass.GENERAL_APPROVED})
    assert (policy.max_input_tokens, policy.max_output_tokens) == (3_000, 64)
    assert policy.max_cost_usd == Decimal("0.01")
    assert policy.timeout_seconds == 5.0
    assert policy.zdr_requirement is ZDRRequirement.REQUIRED
    assert policy.redaction_requirement is RedactionRequirement.REQUIRED
    assert policy.protection_profile is AIProtectionProfileId.EXTERNAL_MODEL_PII_V1
    assert policy.fallback_policy is AIFallbackPolicy.NO_FALLBACK
    assert policy.allowed_agent_authorities == frozenset({AgentAuthority.READ_AUTHORISED_CONTEXT})


@pytest.mark.parametrize(
    ("constraints", "reason"),
    [
        (
            AIPolicyConstraints(
                allowed_provider_classes=frozenset({AIProviderClass.INTERNAL_ONLY})
            ),
            AIPolicyReasonCode.PROVIDER_CLASS_UNAVAILABLE,
        ),
        (
            AIPolicyConstraints(
                allowed_model_classes=frozenset({AIModelClass.RESTRICTED_DATA_APPROVED})
            ),
            AIPolicyReasonCode.MODEL_CLASS_UNAVAILABLE,
        ),
    ],
)
def test_empty_provider_or_model_intersection_denies(
    constraints: AIPolicyConstraints,
    reason: AIPolicyReasonCode,
) -> None:
    override = _rule(rule_id=f"test.{reason.value.lower()}", constraints=constraints)
    decision = _engine(repository=StaticAIPolicyRepository(override_rules=(override,))).evaluate(
        session=None, request=_request()
    )
    assert decision.decision is AIPolicyOutcome.DENY
    assert decision.reason_code is reason


def test_broad_override_cannot_widen_baseline_permissions_or_budgets() -> None:
    broad_override = _rule(
        rule_id="test.cannot-widen",
        constraints=AIPolicyConstraints(
            allowed_provider_classes=frozenset(set(AIProviderClass)),
            allowed_model_classes=frozenset(set(AIModelClass)),
            max_input_tokens=99_999,
            max_output_tokens=99_999,
            max_cost_usd=Decimal("999"),
            timeout_seconds=999.0,
            zdr_requirement=ZDRRequirement.NOT_REQUIRED,
            redaction_requirement=RedactionRequirement.NOT_REQUIRED,
            fallback_policy=AIFallbackPolicy.SAME_SECURITY_CLASS_ONLY,
            allowed_agent_authorities=frozenset(set(AgentAuthority)),
        ),
    )
    decision = _engine(
        repository=StaticAIPolicyRepository(override_rules=(broad_override,))
    ).evaluate(session=None, request=_request())
    policy = decision.effective_policy
    assert policy is not None
    assert (policy.max_input_tokens, policy.max_output_tokens) == (4_096, 128)
    assert policy.max_cost_usd == Decimal("0.05")
    assert policy.timeout_seconds == 20.0
    assert policy.zdr_requirement is ZDRRequirement.REQUIRED
    assert policy.fallback_policy is AIFallbackPolicy.NO_FALLBACK
    assert policy.allowed_agent_authorities == BUILD0_AGENT_AUTHORITY_CEILING


def test_sensitivity_controls_are_monotonic_when_task_is_explicitly_registered() -> None:
    engine = _engine(registry=_registry_for_all_sensitivities())
    policies = {
        sensitivity: engine.evaluate(
            session=None,
            request=_request(sensitivity=sensitivity),
        ).effective_policy
        for sensitivity in SensitivityLevel
    }
    standard = policies[SensitivityLevel.STANDARD]
    sensitive = policies[SensitivityLevel.SENSITIVE]
    restricted = policies[SensitivityLevel.RESTRICTED]
    assert standard is not None and sensitive is not None and restricted is not None
    assert restricted.allowed_provider_classes <= sensitive.allowed_provider_classes
    assert sensitive.allowed_provider_classes <= standard.allowed_provider_classes
    assert restricted.max_input_tokens <= sensitive.max_input_tokens <= standard.max_input_tokens
    assert restricted.max_output_tokens <= sensitive.max_output_tokens <= standard.max_output_tokens
    assert restricted.max_cost_usd <= sensitive.max_cost_usd <= standard.max_cost_usd
    assert sensitive.redaction_requirement is RedactionRequirement.REQUIRED
    assert restricted.redaction_requirement is RedactionRequirement.REQUIRED
    assert sensitive.protection_profile is AIProtectionProfileId.EXTERNAL_MODEL_PII_V1
    assert restricted.protection_profile is AIProtectionProfileId.EXTERNAL_MODEL_PII_V1


def test_missing_or_invalid_sensitivity_cannot_create_policy_context() -> None:
    valid = trusted_ai_context().model_dump()
    with pytest.raises(ValidationError):
        ExecutionContext.model_validate({**valid, "effective_sensitivity": None})
    with pytest.raises(ValidationError):
        ExecutionContext.model_validate({**valid, "effective_sensitivity": "SECRET"})


def test_decision_and_effective_policy_are_immutable() -> None:
    decision = _engine().evaluate(session=None, request=_request())
    assert decision.effective_policy is not None
    with pytest.raises(ValidationError):
        decision.reason_code = AIPolicyReasonCode.ALLOWED
    with pytest.raises(ValidationError):
        decision.effective_policy.max_output_tokens = 999_999


def test_relevant_policy_change_changes_version_hash_and_fingerprint() -> None:
    v1 = _engine().evaluate(session=None, request=_request())
    restrictive = _rule(
        rule_id="test.versioned",
        revision=2,
        constraints=AIPolicyConstraints(max_output_tokens=64),
    )
    v2 = _engine(repository=StaticAIPolicyRepository(override_rules=(restrictive,))).evaluate(
        session=None, request=_request()
    )
    assert v1.policy_version != v2.policy_version
    assert v1.policy_hash != v2.policy_hash
    assert v1.decision_fingerprint != v2.decision_fingerprint
    assert v2.effective_policy is not None
    assert v2.effective_policy.max_output_tokens == 64


def test_policy_telemetry_is_structured_and_excludes_untrusted_content() -> None:
    sentinel = "TOP_SECRET_POLICY_TEST_SENTINEL"
    request = _request()
    with _captured_policy_logs() as output:
        decision = _engine().evaluate(session=None, request=request)
    logged = output.getvalue()
    event = json.loads(logged.strip())
    assert event["event"] == "ai.policy.evaluated"
    assert event["decision"] == AIPolicyOutcome.ALLOW.value
    assert event["reason_code"] == AIPolicyReasonCode.ALLOWED.value
    assert event["policy_version"] == decision.policy_version
    assert event["task"] == AITaskType.SYNTHETIC_TEXT_SUMMARY.value
    assert event["sensitivity"] == SensitivityLevel.STANDARD.value
    assert event["protection_profile"] == AIProtectionProfileId.NONE.value
    assert "prompt" not in event
    assert "input_data" not in event
    assert "document_body" not in event
    assert sentinel not in logged


def test_unknown_task_request_cannot_be_revalidated_as_registered_task() -> None:
    request = _request()
    with pytest.raises(ValidationError):
        AIPolicyEvaluationRequest.model_validate(
            {**request.model_dump(), "task": cast(AITaskType, "removed_task")}
        )
