from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fixtures.ai_gateway import NOOP_AI_PROVENANCE, FakeAIProvider, build_test_model_route
from fixtures.tenant_foundation import (
    ALICE_ID,
    ALICE_MEMBERSHIP_ID,
    APOLLO_FINANCE_ID,
    BOB_ID,
    BOB_MEMBERSHIP_ID,
    FIRM_A_ID,
    FIRM_B_ID,
    NORTHSTAR_RETAIL_ID,
)
from sqlalchemy import Engine, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from privexa_api.access_control.context import FirmContext
from privexa_api.access_control.enums import FirmRole
from privexa_api.access_control.permissions import Permission
from privexa_api.access_control.service import AccessControlService
from privexa_api.ai_gateway.contracts import AIExecutionRequest, AIExecutionStatus
from privexa_api.ai_gateway.errors import AIErrorCategory
from privexa_api.ai_gateway.gateway import AIGateway
from privexa_api.ai_gateway.routing import AIModelRouter, AIProviderName
from privexa_api.ai_gateway.tasks import SyntheticTextSummaryInput, build_task_registry
from privexa_api.ai_gateway.telemetry import AIExecutionTelemetry
from privexa_api.ai_policy.contracts import AIPolicyEvaluationRequest, AIPolicyOutcome
from privexa_api.ai_policy.errors import InvalidAIPolicyConfiguration
from privexa_api.ai_policy.evaluator import AIPolicyEvaluator
from privexa_api.ai_policy.models import AIPolicyOverride, AIPolicyRuntimeControl
from privexa_api.ai_policy.registry import build_policy_registry
from privexa_api.ai_policy.repository import DatabaseAIPolicyRepository
from privexa_api.ai_policy.service import AIPolicyEngine
from privexa_api.ai_types import AITaskType
from privexa_api.authentication.principal import AuthenticatedPrincipal
from privexa_api.security.enums import OriginatingChannel, SensitivityLevel
from privexa_api.security.execution_context import ExecutionContext, issue_execution_context

pytestmark = [pytest.mark.security, pytest.mark.tenant_isolation]


def _configuration_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runtime_control(
    *,
    task_id: str | None,
    enabled: bool,
    revision: int = 1,
) -> AIPolicyRuntimeControl:
    return AIPolicyRuntimeControl(
        id=uuid4(),
        task_id=task_id,
        enabled=enabled,
        revision=revision,
        configuration_hash=_configuration_hash(
            {"task_id": task_id, "enabled": enabled, "revision": revision}
        ),
    )


def _reset_runtime_controls(engine: Engine, *, global_enabled: bool) -> None:
    with Session(engine) as session, session.begin():
        session.execute(text("TRUNCATE TABLE ai_policy_runtime_controls"))
        session.add_all(
            [
                _runtime_control(task_id=None, enabled=global_enabled),
                _runtime_control(
                    task_id=AITaskType.SYNTHETIC_TEXT_SUMMARY.value,
                    enabled=True,
                ),
                _runtime_control(
                    task_id=AITaskType.PREPARE_WORK_NOTE.value,
                    enabled=True,
                ),
            ]
        )


@pytest.fixture
def enabled_policy_controls(
    owner_engine: Engine,
    migrated_database: None,
) -> Iterator[None]:
    _reset_runtime_controls(owner_engine, global_enabled=True)
    try:
        yield
    finally:
        _reset_runtime_controls(owner_engine, global_enabled=False)


def _override(
    *,
    firm_id: UUID,
    client_id: UUID | None,
    constraints: dict[str, object],
    revision: int = 1,
    task_id: str | None = AITaskType.SYNTHETIC_TEXT_SUMMARY.value,
    sensitivity: str | None = SensitivityLevel.STANDARD.value,
    configuration_hash: str | None = None,
) -> AIPolicyOverride:
    canonical = {
        "firm_id": str(firm_id),
        "client_id": str(client_id) if client_id is not None else None,
        "task": task_id,
        "sensitivity": sensitivity,
        "revision": revision,
        "constraints": constraints,
    }
    return AIPolicyOverride(
        id=uuid4(),
        firm_id=firm_id,
        client_id=client_id,
        task_id=task_id,
        sensitivity=sensitivity,
        constraints=constraints,
        revision=revision,
        configuration_hash=configuration_hash or _configuration_hash(canonical),
    )


def _principal(
    *,
    user_id: UUID,
    membership_id: UUID,
    firm_id: UUID,
    role: FirmRole = FirmRole.CONSULTANT,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        firm_context=FirmContext(
            user_id=user_id,
            membership_id=membership_id,
            firm_id=firm_id,
            role=role,
        ),
        stytch_member_id=f"member-{user_id}",
        stytch_organization_id=f"organization-{firm_id}",
        stytch_member_session_id=f"session-{membership_id}",
    )


ALICE = _principal(
    user_id=ALICE_ID,
    membership_id=ALICE_MEMBERSHIP_ID,
    firm_id=FIRM_A_ID,
)
BOB = _principal(
    user_id=BOB_ID,
    membership_id=BOB_MEMBERSHIP_ID,
    firm_id=FIRM_B_ID,
)


def _context(
    session: Session,
    *,
    principal: AuthenticatedPrincipal,
    client_id: UUID,
) -> ExecutionContext:
    authorization = AccessControlService.authorize_client(
        session,
        principal=principal,
        client_id=client_id,
        permission=Permission.CLIENT_READ,
    )
    return issue_execution_context(
        authorization=authorization,
        request_id=uuid4(),
        trace_id=None,
        effective_sensitivity=SensitivityLevel.STANDARD,
        originating_channel=OriginatingChannel.WEB,
    )


def _policy_engine() -> AIPolicyEngine:
    return AIPolicyEngine(
        evaluator=AIPolicyEvaluator(build_policy_registry()),
        repository=DatabaseAIPolicyRepository(),
        deployment_enabled=True,
    )


def _policy_request(context: ExecutionContext) -> AIPolicyEvaluationRequest:
    task = build_task_registry().resolve(AITaskType.SYNTHETIC_TEXT_SUMMARY)
    return AIPolicyEvaluationRequest(
        context=context,
        task=task.task,
        task_version=task.version,
        required_scope=task.required_scope,
        required_permission=task.required_permission,
        requested_agent_authorities=task.requested_agent_authorities,
    )


def _gateway(provider: FakeAIProvider) -> AIGateway:
    route = build_test_model_route()
    return AIGateway(
        registry=build_task_registry(),
        policy=_policy_engine(),
        router=AIModelRouter(
            {route.alias: route},
            approved_provider_models=frozenset({route.provider_model}),
        ),
        providers={AIProviderName.OPENROUTER: provider},
        telemetry=AIExecutionTelemetry(),
        provenance=NOOP_AI_PROVENANCE,
    )


def _execution_request() -> AIExecutionRequest:
    return AIExecutionRequest(
        task=AITaskType.SYNTHETIC_TEXT_SUMMARY,
        input_data=SyntheticTextSummaryInput(text="Synthetic tenant policy input."),
    )


def test_rls_returns_only_current_tenant_policy_rows(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(owner_engine) as owner, owner.begin():
        owner.add_all(
            [
                _override(
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    constraints={"max_output_tokens": 64},
                ),
                _override(
                    firm_id=FIRM_B_ID,
                    client_id=NORTHSTAR_RETAIL_ID,
                    constraints={"max_output_tokens": 32},
                ),
            ]
        )

    with Session(app_engine) as session, session.begin():
        _context(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        alice_rows = [
            (row.firm_id, row.client_id) for row in session.scalars(select(AIPolicyOverride)).all()
        ]
    with Session(app_engine) as session, session.begin():
        _context(session, principal=BOB, client_id=NORTHSTAR_RETAIL_ID)
        bob_rows = [
            (row.firm_id, row.client_id) for row in session.scalars(select(AIPolicyOverride)).all()
        ]

    assert alice_rows == [(FIRM_A_ID, APOLLO_FINANCE_ID)]
    assert bob_rows == [(FIRM_B_ID, NORTHSTAR_RETAIL_ID)]


@pytest.mark.asyncio
async def test_tenant_policies_remain_isolated_when_execution_order_alternates(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(owner_engine) as owner, owner.begin():
        owner.add_all(
            [
                _override(
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    constraints={"max_output_tokens": 64},
                ),
                _override(
                    firm_id=FIRM_B_ID,
                    client_id=NORTHSTAR_RETAIL_ID,
                    constraints={"enabled": False},
                ),
            ]
        )

    provider = FakeAIProvider()
    gateway = _gateway(provider)
    outcomes: list[AIExecutionStatus] = []
    for principal, client_id in [
        (ALICE, APOLLO_FINANCE_ID),
        (BOB, NORTHSTAR_RETAIL_ID),
        (ALICE, APOLLO_FINANCE_ID),
        (BOB, NORTHSTAR_RETAIL_ID),
    ]:
        with Session(app_engine) as session, session.begin():
            context = _context(session, principal=principal, client_id=client_id)
            result = await gateway.execute(
                context=context,
                request=_execution_request(),
                session=session,
            )
            outcomes.append(result.status)

    assert outcomes == [
        AIExecutionStatus.SUCCEEDED,
        AIExecutionStatus.REJECTED,
        AIExecutionStatus.SUCCEEDED,
        AIExecutionStatus.REJECTED,
    ]
    assert len(provider.requests) == 2
    assert {request.max_output_tokens for request in provider.requests} == {64}


@pytest.mark.asyncio
async def test_database_session_and_security_context_mismatch_fails_before_provider(
    tenant_data,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(app_engine) as bob_session, bob_session.begin():
        bob_context = _context(
            bob_session,
            principal=BOB,
            client_id=NORTHSTAR_RETAIL_ID,
        )

    provider = FakeAIProvider()
    gateway = _gateway(provider)
    with Session(app_engine) as alice_session, alice_session.begin():
        _context(alice_session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        result = await gateway.execute(
            context=bob_context,
            request=_execution_request(),
            session=alice_session,
        )

    assert result.status is AIExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.INTERNAL_ERROR
    assert provider.requests == []


@pytest.mark.parametrize(
    "invalid_override",
    [
        _override(
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            constraints={"max_output_tokens": 64},
            configuration_hash="0" * 64,
        ),
        _override(
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            constraints={"max_ouput_tokens": 64},
        ),
    ],
)
@pytest.mark.asyncio
async def test_corrupt_or_misspelled_tenant_policy_fails_closed_before_provider(
    invalid_override: AIPolicyOverride,
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(owner_engine) as owner, owner.begin():
        owner.add(invalid_override)

    provider = FakeAIProvider()
    gateway = _gateway(provider)
    with Session(app_engine) as session, session.begin():
        context = _context(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        result = await gateway.execute(
            context=context,
            request=_execution_request(),
            session=session,
        )

    assert result.status is AIExecutionStatus.REJECTED
    assert result.error is not None
    assert result.error.category is AIErrorCategory.POLICY_DENIED
    assert provider.requests == []


@pytest.mark.asyncio
async def test_runtime_global_kill_switch_change_is_effective_on_next_lookup(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    provider = FakeAIProvider()
    gateway = _gateway(provider)
    with Session(app_engine) as session, session.begin():
        context = _context(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        allowed = await gateway.execute(
            context=context,
            request=_execution_request(),
            session=session,
        )

    now = datetime.now(UTC)
    with Session(owner_engine) as owner, owner.begin():
        owner.execute(
            update(AIPolicyRuntimeControl)
            .where(
                AIPolicyRuntimeControl.task_id.is_(None),
                AIPolicyRuntimeControl.superseded_at.is_(None),
            )
            .values(superseded_at=now)
        )
        owner.add(_runtime_control(task_id=None, enabled=False, revision=2))

    with Session(app_engine) as session, session.begin():
        context = _context(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        denied = await gateway.execute(
            context=context,
            request=_execution_request(),
            session=session,
        )

    assert allowed.status is AIExecutionStatus.SUCCEEDED
    assert denied.status is AIExecutionStatus.REJECTED
    assert denied.error is not None
    assert denied.error.category is AIErrorCategory.GATEWAY_DISABLED
    assert len(provider.requests) == 1


def test_policy_version_changes_after_authoritative_override_revision(
    tenant_data,
    owner_engine: Engine,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    original = _override(
        firm_id=FIRM_A_ID,
        client_id=APOLLO_FINANCE_ID,
        constraints={"max_output_tokens": 64},
    )
    original_id = original.id
    with Session(owner_engine) as owner, owner.begin():
        owner.add(original)

    engine = _policy_engine()
    with Session(app_engine) as session, session.begin():
        context = _context(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        v1 = engine.evaluate(session=session, request=_policy_request(context))

    with Session(owner_engine) as owner, owner.begin():
        current = owner.get(AIPolicyOverride, original_id)
        assert current is not None
        current.superseded_at = datetime.now(UTC)
        owner.add(
            _override(
                firm_id=FIRM_A_ID,
                client_id=APOLLO_FINANCE_ID,
                constraints={"max_output_tokens": 32},
                revision=2,
            )
        )

    with Session(app_engine) as session, session.begin():
        context = _context(session, principal=ALICE, client_id=APOLLO_FINANCE_ID)
        v2 = engine.evaluate(session=session, request=_policy_request(context))

    assert v1.decision is AIPolicyOutcome.ALLOW
    assert v2.decision is AIPolicyOutcome.ALLOW
    assert v1.policy_version != v2.policy_version
    assert v1.decision_fingerprint != v2.decision_fingerprint
    assert v1.effective_policy is not None and v2.effective_policy is not None
    assert (v1.effective_policy.max_output_tokens, v2.effective_policy.max_output_tokens) == (
        64,
        32,
    )


def test_startup_validation_rejects_corrupt_runtime_control(
    owner_engine: Engine,
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(owner_engine) as owner, owner.begin():
        owner.execute(
            update(AIPolicyRuntimeControl)
            .where(AIPolicyRuntimeControl.task_id.is_(None))
            .values(configuration_hash="0" * 64)
        )

    with (
        Session(app_engine) as session,
        session.begin(),
        pytest.raises(InvalidAIPolicyConfiguration, match="hash mismatch"),
    ):
        _policy_engine().validate_startup(session)


@pytest.mark.parametrize(
    "invalid_override",
    [
        _override(
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            constraints={"enabled": False},
            revision=0,
        ),
        _override(
            firm_id=FIRM_A_ID,
            client_id=APOLLO_FINANCE_ID,
            constraints={"enabled": False},
            sensitivity="SECRET",
        ),
        _override(
            firm_id=FIRM_A_ID,
            client_id=NORTHSTAR_RETAIL_ID,
            constraints={"enabled": False},
        ),
    ],
)
def test_database_rejects_invalid_revision_sensitivity_or_tenant_foreign_key(
    invalid_override: AIPolicyOverride,
    tenant_data,
    owner_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(owner_engine) as owner, pytest.raises(IntegrityError), owner.begin():
        owner.add(invalid_override)
        owner.flush()


def test_database_rejects_duplicate_current_policy_scope(
    tenant_data,
    owner_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(owner_engine) as owner, pytest.raises(IntegrityError), owner.begin():
        owner.add_all(
            [
                _override(
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    constraints={"max_output_tokens": 64},
                    revision=1,
                ),
                _override(
                    firm_id=FIRM_A_ID,
                    client_id=APOLLO_FINANCE_ID,
                    constraints={"max_output_tokens": 32},
                    revision=2,
                ),
            ]
        )
        owner.flush()


def test_runtime_role_has_read_only_policy_table_privileges(
    app_engine: Engine,
    enabled_policy_controls: None,
) -> None:
    with Session(app_engine) as session, pytest.raises(DBAPIError) as error, session.begin():
        session.execute(
            update(AIPolicyRuntimeControl)
            .where(AIPolicyRuntimeControl.task_id.is_(None))
            .values(enabled=False)
        )

    assert getattr(error.value.orig, "sqlstate", None) == "42501"


def test_policy_tables_and_indexes_are_present_with_forced_rls(owner_engine: Engine) -> None:
    with owner_engine.connect() as connection:
        override_security = connection.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'ai_policy_overrides'"
            )
        ).one()
        indexes = set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                    "AND tablename IN ('ai_policy_overrides', 'ai_policy_runtime_controls')"
                )
            ).scalars()
        )

    assert override_security.relrowsecurity is True
    assert override_security.relforcerowsecurity is True
    assert {
        "ix_ai_policy_overrides_current_lookup",
        "uq_ai_policy_overrides_current_scope",
        "uq_ai_policy_runtime_controls_current_global",
        "uq_ai_policy_runtime_controls_current_task",
    } <= indexes
