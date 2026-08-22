from __future__ import annotations

import pytest
from fixtures.ai_gateway import trusted_ai_context
from pydantic import ValidationError

from privexa_api.access_control.permissions import AuthorizationScope, Permission
from privexa_api.ai_policy.contracts import (
    AgentAuthority,
    AIPolicyEvaluationRequest,
    AIPolicyOutcome,
    AIPolicyReasonCode,
)
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import StaticAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_types import AITaskType


def _engine(*, enabled: bool = True) -> AIPolicyEngine:
    registry = build_policy_registry()
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(registry),
        repository=StaticAIPolicyRepository(),
        deployment_enabled=enabled,
    )


def _request(*, authorities: frozenset[AgentAuthority]) -> AIPolicyEvaluationRequest:
    return AIPolicyEvaluationRequest(
        context=trusted_ai_context(),
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        task_version="1",
        required_scope=AuthorizationScope.CLIENT,
        required_permission=Permission.CLIENT_READ,
        requested_agent_authorities=authorities,
    )


def test_registered_standard_task_receives_immutable_allow_envelope() -> None:
    request = _request(
        authorities=frozenset(
            {
                AgentAuthority.READ_AUTHORISED_CONTEXT,
                AgentAuthority.PREPARE_PROPOSED_OUTPUT,
            }
        )
    )

    decision = _engine().evaluate(session=None, request=request)

    assert decision.decision is AIPolicyOutcome.ALLOW
    assert decision.reason_code is AIPolicyReasonCode.ALLOWED
    assert decision.effective_policy is not None
    assert decision.policy_version.startswith("build0-v1:")
    with pytest.raises(ValidationError):
        decision.effective_policy.max_output_tokens = 9_999


def test_build0_authority_escalation_is_denied() -> None:
    request = _request(
        authorities=frozenset(
            {
                AgentAuthority.READ_AUTHORISED_CONTEXT,
                AgentAuthority.EXTERNAL_COMMUNICATION,
            }
        )
    )

    decision = _engine().evaluate(session=None, request=request)

    assert decision.decision is AIPolicyOutcome.DENY
    assert decision.reason_code is AIPolicyReasonCode.AUTHORITY_DENIED
    assert decision.effective_policy is None


def test_semantically_identical_evaluations_have_same_fingerprint() -> None:
    context = trusted_ai_context()
    request = AIPolicyEvaluationRequest(
        context=context,
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        task_version="1",
        required_scope=AuthorizationScope.CLIENT,
        required_permission=Permission.CLIENT_READ,
        requested_agent_authorities=frozenset(
            {
                AgentAuthority.READ_AUTHORISED_CONTEXT,
                AgentAuthority.PREPARE_PROPOSED_OUTPUT,
            }
        ),
    )
    engine = _engine()

    first = engine.evaluate(session=None, request=request)
    second = engine.evaluate(session=None, request=request)

    assert first.decision_id != second.decision_id
    assert first.decision_fingerprint == second.decision_fingerprint
    assert first.policy_hash == second.policy_hash
